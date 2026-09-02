from fastapi import APIRouter, Depends, Header, HTTPException, status
from typing import Optional
import datetime
import secrets
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.app.database import get_db
from backend.app.models import AgentTrustScore
from backend.app.schemas import (
    AgentRegisterRequest, AgentRegisterResponse,
    MandateIssueRequest, MandateIssueResponse, BuyerMandate
)
from backend.app.middleware.auth import generate_agent_key, hash_agent_key
from backend.app.services.mandate_service import sign_mandate

router = APIRouter(prefix="/api/agents", tags=["Agent Identity"])


@router.post("/register", response_model=AgentRegisterResponse, status_code=status.HTTP_201_CREATED)
def register_agent(req: AgentRegisterRequest, db: Session = Depends(get_db)):
    """
    Explicit, visible agent registration step (A1).

    Issues a real random secret (secrets.token_urlsafe(32)) for a brand-new
    agent_id and returns it exactly once. Only its HMAC hash is ever stored.
    Callers MUST persist the returned agent_key and send it as the
    'X-Agent-Key' header on every subsequent /api/negotiate, /api/checkout,
    or /api/agents/{agent_id}/mandates request for this agent_id.

    Re-registering an agent_id that already has a key is rejected with 409 -
    keys are never silently reissued or rotated by this endpoint.
    """
    existing = db.query(AgentTrustScore).filter(AgentTrustScore.agent_id == req.agent_id).first()
    if existing and existing.agent_key_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Agent '{req.agent_id}' is already registered. "
                "Use the X-Agent-Key issued at first registration; keys are not reissued."
            )
        )

    new_key = generate_agent_key()
    key_hash = hash_agent_key(new_key)

    if existing:
        # Record exists (e.g. legacy row with no key hash) but has no key yet.
        existing.agent_key_hash = key_hash
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Registration race; try again.")
    else:
        trust_record = AgentTrustScore(agent_id=req.agent_id, trust_score=0.5, agent_key_hash=key_hash)
        db.add(trust_record)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Registration race; try again.")

    return AgentRegisterResponse(agent_id=req.agent_id, agent_key=new_key)


@router.post("/{agent_id}/mandates", response_model=MandateIssueResponse)
def issue_mandate(
    agent_id: str,
    req: MandateIssueRequest,
    x_agent_key: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    AP2 Mandate Issuance (A4).

    Requires the agent's real, already-issued X-Agent-Key (from
    POST /api/agents/register). Signs and returns a BuyerMandate the
    agent can attach as `mandate` / `mandate_signature` on
    /api/negotiate or /api/checkout - using the exact same
    sign_mandate()/evaluate_buyer_mandate() logic pytest already
    exercises internally, now reachable by a real agent over HTTP.

    Unlike negotiate/checkout, this endpoint does NOT auto-provision a
    key for an unseen agent_id: mandate issuance is a sensitive,
    high-trust operation, so identity must already be established via
    /api/agents/register before a mandate can be requested.
    """
    trust_record = db.query(AgentTrustScore).filter(AgentTrustScore.agent_id == agent_id).first()
    if not trust_record or not trust_record.agent_key_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                f"Agent '{agent_id}' is not registered. "
                "Call POST /api/agents/register first to obtain a key, "
                "then retry with the X-Agent-Key header set."
            )
        )

    key_str = x_agent_key if isinstance(x_agent_key, str) and x_agent_key.strip() else None
    if not key_str or not secrets.compare_digest(trust_record.agent_key_hash, hash_agent_key(key_str)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed for agent '{agent_id}'. Missing or invalid X-Agent-Key header."
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    valid_until = now + datetime.timedelta(minutes=req.valid_minutes)

    mandate = BuyerMandate(
        agent_id=agent_id,
        sku=req.sku,
        max_unit_price=req.max_unit_price,
        max_discount_pct=req.max_discount_pct,
        max_quantity=req.max_quantity,
        valid_until=valid_until,
        issued_at=now
    )
    signature = sign_mandate(mandate)

    return MandateIssueResponse(mandate=mandate, mandate_signature=signature)
