import hmac
import hashlib
import time
import secrets
from typing import Optional, Dict
from fastapi import Header, HTTPException, Depends, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from backend.app.database import get_db
from backend.app.config import settings
from backend.app.models import AgentTrustScore

security = HTTPBasic()

# In-memory rate limiting tracker: ip/agent -> [timestamps]
RATE_LIMIT_BUCKETS: Dict[str, list] = {}

def get_current_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """
    HTTP Basic Authentication for Merchant Admin routes.
    """
    correct_username = secrets.compare_digest(credentials.username, settings.ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, settings.ADMIN_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid merchant administrator credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

def hash_agent_key(api_key: str) -> str:
    if not isinstance(api_key, str):
        api_key = str(api_key or "")
    return hmac.new(
        key=settings.AGENT_AUTH_SECRET.encode("utf-8"),
        msg=api_key.encode("utf-8"),
        digestmod=hashlib.sha256
    ).hexdigest()

def generate_agent_key() -> str:
    """Generates a real, non-guessable agent secret. Never derived from agent_id."""
    return secrets.token_urlsafe(32)

def verify_or_provision_agent_key(
    agent_id: Optional[str],
    x_agent_key: Optional[str],
    db: Session
) -> Optional[str]:
    """
    Agent Identity Scheme (A1 - hardened):
    - Brand-new agent_id + no key supplied -> provision a real random secret,
      store only its HMAC hash, and return the raw key ONCE so the caller
      (e.g. the /api/agents/register route, or a first-touch negotiate/checkout
      call) can hand it back to the agent. There is no guessable default key.
    - Any agent_id that already has a stored key hash MUST present a matching
      X-Agent-Key header, or the request is rejected with 401. No silent
      fallback to a derived/default key.
    - Returns the newly-generated raw key only on first provisioning; returns
      None otherwise (key was already known to / verified against the caller).
    """
    if not agent_id:
        return None

    key_str = x_agent_key if isinstance(x_agent_key, str) and x_agent_key.strip() else None
    trust_record = db.query(AgentTrustScore).filter(AgentTrustScore.agent_id == agent_id).first()

    if not trust_record:
        # Brand-new agent: mint a real secret, persist only its hash.
        new_key = generate_agent_key()
        trust_record = AgentTrustScore(
            agent_id=agent_id,
            trust_score=0.5,
            agent_key_hash=hash_agent_key(new_key)
        )
        try:
            db.add(trust_record)
            db.flush()
            return new_key
        except IntegrityError:
            # Lost a race with a concurrent first-use request; fall through
            # to standard verification against whatever key won the race.
            db.rollback()
            trust_record = db.query(AgentTrustScore).filter(AgentTrustScore.agent_id == agent_id).first()

    # Existing agent: a stored key hash MUST be matched. No default fallback.
    if trust_record and trust_record.agent_key_hash:
        if not key_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    f"Agent '{agent_id}' is already registered. "
                    "Missing X-Agent-Key header. Use the key issued when you "
                    "first registered (see POST /api/agents/register)."
                )
            )
        provided_hash = hash_agent_key(key_str)
        if not secrets.compare_digest(trust_record.agent_key_hash, provided_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Authentication failed for agent '{agent_id}'. Invalid X-Agent-Key header."
            )

    return None

def check_rate_limit(
    request: Request,
    agent_id: Optional[str] = None
):
    """
    Sliding window rate limiter: 30 requests per minute per IP / agent_id.
    """
    if not request:
        return
    client_ip = request.client.host if request.client else "unknown"
    key = f"rate:{agent_id or client_ip}"
    now = time.time()
    window = 60.0
    limit = settings.RATE_LIMIT_PER_MINUTE

    timestamps = RATE_LIMIT_BUCKETS.get(key, [])
    timestamps = [t for t in timestamps if now - t < window]

    if len(timestamps) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded ({limit} requests/minute). Please slow down."
        )

    timestamps.append(now)
    RATE_LIMIT_BUCKETS[key] = timestamps
