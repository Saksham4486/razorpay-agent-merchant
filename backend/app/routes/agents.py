from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.app.database import get_db
from backend.app.models import AgentTrustScore
from backend.app.schemas import AgentRegisterRequest, AgentRegisterResponse
from backend.app.middleware.auth import generate_agent_key, hash_agent_key

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
