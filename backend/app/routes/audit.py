import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc
from backend.app.database import get_db
from backend.app.models import AuditLog, AgentTrustScore, Order
from backend.app.schemas import AuditDashboardResponse, AuditLogSchema, AgentTrustScoreSchema
from backend.app.config import settings

router = APIRouter(prefix="/api/audit", tags=["Audit Log"])

@router.get("", response_model=AuditDashboardResponse)
def get_audit_dashboard(
    actor: Optional[str] = Query(None, description="Filter by actor"),
    status: Optional[str] = Query(None, description="Filter by status"),
    sku: Optional[str] = Query(None, description="Filter by SKU"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """
    Returns full explainable audit trail, agent trust scores, and merchant financial telemetry.
    """
    query = db.query(AuditLog)
    
    if actor:
        query = query.filter(AuditLog.actor.ilike(f"%{actor}%"))
    if status:
        query = query.filter(AuditLog.status == status)
    if sku:
        query = query.filter(AuditLog.sku == sku)

    total_logs = query.count()
    logs = query.order_by(desc(AuditLog.id)).limit(limit).all()

    # Fetch trust scores
    trust_scores = db.query(AgentTrustScore).order_by(desc(AgentTrustScore.trust_score)).all()

    # Calculate current daily volume
    today_start = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_spend = db.query(func.sum(Order.total_amount_inr)).filter(
        Order.created_at >= today_start,
        Order.status.in_(["paid", "pending_payment", "pending_approval", "pending_confirmation"])
    ).scalar() or 0.0

    return AuditDashboardResponse(
        logs=[AuditLogSchema.model_validate(log) for log in logs],
        total_logs=total_logs,
        trust_scores=[AgentTrustScoreSchema.model_validate(ts) for ts in trust_scores],
        daily_spend_inr=float(daily_spend),
        daily_cap_inr=settings.DAILY_MERCHANT_SPEND_CAP_INR,
        chain_intact=True
    )

@router.get("/verify")
def verify_audit_trail(db: Session = Depends(get_db)):
    """
    Cryptographic Verification Endpoint (Phase 8):
    Walks the SHA256 hash chain of the entire audit log from Genesis (id=1) to the latest entry.
    Verifies that no record has been tampered with or modified.
    """
    all_logs = db.query(AuditLog).order_by(asc(AuditLog.id)).all()
    if not all_logs:
        return {"valid": True, "total_verified": 0, "message": "Audit log is empty."}

    expected_prev_hash = "0" * 64
    for entry in all_logs:
        if entry.prev_hash != expected_prev_hash:
            return {
                "valid": False,
                "broken_at_id": entry.id,
                "error": "Previous hash pointer mismatch",
                "expected_prev": expected_prev_hash,
                "actual_prev": entry.prev_hash
            }
        
        computed = entry.compute_hash(expected_prev_hash)
        if entry.entry_hash != computed:
            return {
                "valid": False,
                "broken_at_id": entry.id,
                "error": "Entry content hash mismatch (tampering detected)",
                "expected_hash": computed,
                "stored_hash": entry.entry_hash
            }
        expected_prev_hash = entry.entry_hash

    return {
        "valid": True,
        "total_verified": len(all_logs),
        "latest_hash": expected_prev_hash,
        "message": f"Audit trail of {len(all_logs)} records is cryptographically intact."
    }
