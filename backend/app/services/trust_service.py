import datetime
from sqlalchemy.orm import Session
from backend.app.models import AgentTrustScore, utcnow

def get_or_create_trust_score(db: Session, agent_id: str) -> AgentTrustScore:
    record = db.query(AgentTrustScore).filter(AgentTrustScore.agent_id == agent_id).first()
    if not record:
        record = AgentTrustScore(
            agent_id=agent_id,
            total_orders=0,
            paid_orders=0,
            failed_orders=0,
            rejected_orders=0,
            trust_score=0.5,
            last_updated=utcnow()
        )
        db.add(record)
        db.commit()
        db.refresh(record)
    return record

def calculate_trust_score(paid: int, total: int) -> float:
    """
    Laplace-smoothed trust calculation:
    (paid + 1) / (total + 2)
    Yields 0.5 for fresh agents with 0 orders.
    Climbs towards 1.0 with consistent paid orders.
    Drops towards 0.0 with high failure rates.
    """
    if total < 0 or paid < 0:
        return 0.5
    score = (paid + 1.0) / (total + 2.0)
    return round(max(0.05, min(0.99, score)), 4)

def record_agent_order_outcome(db: Session, agent_id: str, outcome: str):
    """
    outcome: 'paid' | 'failed' | 'rejected'
    """
    if not agent_id:
        return
    
    record = get_or_create_trust_score(db, agent_id)
    record.total_orders += 1
    
    if outcome == "paid":
        record.paid_orders += 1
    elif outcome == "failed":
        record.failed_orders += 1
    elif outcome == "rejected":
        record.rejected_orders += 1
        
    record.trust_score = calculate_trust_score(record.paid_orders, record.total_orders)
    record.last_updated = utcnow()
    
    db.commit()
    db.refresh(record)
    return record
