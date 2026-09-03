from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.schemas import GrowthSummaryResponse
from backend.app.services.growth_service import compute_growth_summary

router = APIRouter(prefix="/api/growth", tags=["Growth Analytics"])


@router.get("/summary", response_model=GrowthSummaryResponse)
def get_growth_summary(db: Session = Depends(get_db)):
    """
    Real growth/revenue numbers pulled directly from the Order and AuditLog
    tables (D2) - ads generated -> chat sessions started -> negotiations
    attempted -> orders completed -> revenue, plus a comparison of
    AI-negotiated orders vs a flat no-negotiation baseline, both derived
    from the same underlying order data. No fabricated numbers.
    """
    summary = compute_growth_summary(db)
    return GrowthSummaryResponse(**summary)
