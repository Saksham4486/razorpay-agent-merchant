from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models import CatalogItem
from backend.app.schemas import CatalogResponse, CatalogItemSchema, CatalogItemPolicy
from backend.app.config import settings

router = APIRouter(prefix="/api/catalog", tags=["Catalog"])

@router.get("", response_model=CatalogResponse)
def get_catalog(db: Session = Depends(get_db)):
    """
    Returns the agent-readable catalog with full pricing and policy thresholds.
    """
    items = db.query(CatalogItem).all()
    schema_items = []
    for item in items:
        schema_items.append(CatalogItemSchema(
            sku=item.sku,
            name=item.name,
            description=item.description,
            category=item.category,
            price_inr=item.price_inr,
            stock=item.stock,
            max_discount_pct=item.max_discount_pct,
            currency=item.currency,
            policy=CatalogItemPolicy(
                min_order_inr=item.min_order_inr,
                requires_approval_above_inr=item.requires_approval_above_inr,
                max_discount_pct=item.max_discount_pct
            ),
            image_url=item.image_url
        ))
    
    return CatalogResponse(
        items=schema_items,
        count=len(schema_items),
        merchant_daily_cap_inr=settings.DAILY_MERCHANT_SPEND_CAP_INR
    )

@router.get("/{sku}", response_model=CatalogItemSchema)
def get_catalog_item(sku: str, db: Session = Depends(get_db)):
    item = db.query(CatalogItem).filter(CatalogItem.sku == sku).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"SKU '{sku}' not found in catalog")
    
    return CatalogItemSchema(
        sku=item.sku,
        name=item.name,
        description=item.description,
        category=item.category,
        price_inr=item.price_inr,
        stock=item.stock,
        max_discount_pct=item.max_discount_pct,
        currency=item.currency,
        policy=CatalogItemPolicy(
            min_order_inr=item.min_order_inr,
            requires_approval_above_inr=item.requires_approval_above_inr,
            max_discount_pct=item.max_discount_pct
        ),
        image_url=item.image_url
    )
