from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models import CatalogItem
from backend.app.schemas import AdGenerateRequest, AdGenerateResponse, MultilingualAdItem
from backend.app.services.llm_service import llm_service
from backend.app.services.audit_service import record_audit_log

router = APIRouter(prefix="/api/ads", tags=["AI Multilingual Ads"])

@router.post("/generate", response_model=AdGenerateResponse)
def generate_ads(req: AdGenerateRequest, db: Session = Depends(get_db)):
    """
    Generates AI-powered multilingual advertising copy for catalog products
    with deep links into the conversational checkout experience.
    """
    item = db.query(CatalogItem).filter(CatalogItem.sku == req.sku).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"SKU '{req.sku}' not found in catalog")

    ad_results = llm_service.generate_multilingual_ads(
        item=item,
        languages=req.languages,
        target_audience=req.target_audience
    )

    gemini_count = sum(1 for a in ad_results if a.get("generated_by") == "gemini")
    record_audit_log(
        db=db,
        actor="growth_engine",
        sku=item.sku,
        requested_discount=0.0,
        order_value_inr=0.0,
        policy_decision="approved",
        reason=f"📢 Generated {len(ad_results)} multilingual ad(s) for {item.name} "
               f"({gemini_count} via Gemini, {len(ad_results) - gemini_count} via template fallback).",
        status="ad_generated",
        metadata={"languages": [a["language_code"] for a in ad_results], "gemini_count": gemini_count}
    )
    db.commit()

    return AdGenerateResponse(
        sku=item.sku,
        product_name=item.name,
        campaign_name=f"Multilingual Growth Engine: {item.name}",
        ads=[MultilingualAdItem(**ad) for ad in ad_results]
    )
