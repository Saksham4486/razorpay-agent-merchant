import json
import logging
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc
from backend.app.models import AuditLog, utcnow

logger = logging.getLogger("audit_service")

def record_audit_log(
    db: Session,
    actor: str,
    sku: str,
    requested_discount: float,
    order_value_inr: float,
    policy_decision: str,
    reason: str,
    status: str,
    agent_id: Optional[str] = None,
    razorpay_order_id: Optional[str] = None,
    failure_detail: Optional[str] = None,
    metadata: Optional[dict] = None
) -> AuditLog:
    """
    Creates an immutable, tamper-evident hash-chained audit log record.
    entry_hash = sha256(prev_hash + serialized row content)
    """
    # Fetch previous entry's hash
    last_log = db.query(AuditLog).order_by(desc(AuditLog.id)).first()
    prev_h = last_log.entry_hash if (last_log and last_log.entry_hash) else "0" * 64

    entry = AuditLog(
        timestamp=utcnow(),
        actor=actor,
        agent_id=agent_id,
        sku=sku,
        requested_discount=requested_discount,
        order_value_inr=order_value_inr,
        policy_decision=policy_decision,
        reason=reason,
        razorpay_order_id=razorpay_order_id,
        status=status,
        failure_detail=failure_detail,
        metadata_json=json.dumps(metadata) if metadata else None,
        prev_hash=prev_h
    )
    entry.entry_hash = entry.compute_hash(prev_h)
    
    db.add(entry)
    return entry
