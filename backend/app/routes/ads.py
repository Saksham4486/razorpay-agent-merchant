from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models import CatalogItem
from backend.app.schemas import AdGenerateRequest, AdGenerateResponse, MultilingualAdItem
from backend.app.services.llm_service import llm_service

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

    return AdGenerateResponse(
        sku=item.sku,
        product_name=item.name,
        campaign_name=f"Multilingual Growth Engine: {item.name}",
        ads=[MultilingualAdItem(**ad) for ad in ad_results]
    )
