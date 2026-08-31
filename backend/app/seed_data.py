from sqlalchemy.orm import Session
from backend.app.models import CatalogItem

INITIAL_SKUS = [
    {
        "sku": "SKU-AI-ROUTER-PRO",
        "name": "Enterprise AI Edge Gateway X1",
        "description": "High-throughput edge computing node with on-device LLM inference acceleration and zero-trust security.",
        "category": "Enterprise Hardware",
        "price_inr": 45000.0,
        "stock": 50,
        "max_discount_pct": 15.0,
        "min_order_inr": 0.0,
        "requires_approval_above_inr": 100000.0,
        "currency": "INR",
        "image_url": "https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?w=500&auto=format&fit=crop&q=60"
    },
    {
        "sku": "SKU-GPU-DEV-BOX",
        "name": "Apex AI Developer Workstation (Dual 48GB)",
        "description": "Dedicated deep learning rig designed for agent developers with liquid cooling and 96GB aggregate VRAM.",
        "category": "Computing",
        "price_inr": 185000.0,
        "stock": 15,
        "max_discount_pct": 10.0,
        "min_order_inr": 0.0,
        "requires_approval_above_inr": 150000.0,  # Single unit triggers pending_approval!
        "currency": "INR",
        "image_url": "https://images.unsplash.com/photo-1587831990711-23ca6441447b?w=500&auto=format&fit=crop&q=60"
    },
    {
        "sku": "SKU-POS-TERMINAL",
        "name": "Razorpay Smart Merchant Android POS",
        "description": "All-in-one wireless Android payment terminal with integrated thermal printer and soundbox alerts.",
        "category": "Merchant Hardware",
        "price_inr": 12500.0,
        "stock": 200,
        "max_discount_pct": 20.0,
        "min_order_inr": 0.0,
        "requires_approval_above_inr": 50000.0,
        "currency": "INR",
        "image_url": "https://images.unsplash.com/photo-1556742049-0a67e5572263?w=500&auto=format&fit=crop&q=60"
    },
    {
        "sku": "SKU-CLOUD-CREDITS",
        "name": "100,000 Autonomous Agent API Credits",
        "description": "Universal LLM token and API transaction credit bundle for merchant automation workflows.",
        "category": "Digital Goods",
        "price_inr": 5000.0,
        "stock": 9999,
        "max_discount_pct": 25.0,
        "min_order_inr": 0.0,
        "requires_approval_above_inr": 25000.0,
        "currency": "INR",
        "image_url": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=500&auto=format&fit=crop&q=60"
    },
    {
        "sku": "SKU-ERGO-DESK",
        "name": "OmniDesk Pro Dual-Motor Standing Desk",
        "description": "Anti-collision dual motor ergonomic motorized sit-stand desk with memory presets and wireless charging pad.",
        "category": "Workspace",
        "price_inr": 28000.0,
        "stock": 40,
        "max_discount_pct": 12.0,
        "min_order_inr": 0.0,
        "requires_approval_above_inr": 60000.0,
        "currency": "INR",
        "image_url": "https://images.unsplash.com/photo-1595515106969-1ce29566ff1c?w=500&auto=format&fit=crop&q=60"
    },
    {
        "sku": "SKU-NOISE-HEADSET",
        "name": "Acoustic Shield Pro ANC Wireless Headset",
        "description": "Active noise cancelling headset with AI beamforming microphone for remote merchant customer support.",
        "category": "Audio",
        "price_inr": 8999.0,
        "stock": 120,
        "max_discount_pct": 18.0,
        "min_order_inr": 0.0,
        "requires_approval_above_inr": 30000.0,
        "currency": "INR",
        "image_url": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500&auto=format&fit=crop&q=60"
    }
]

def seed_catalog(db: Session):
    for item_data in INITIAL_SKUS:
        existing = db.query(CatalogItem).filter(CatalogItem.sku == item_data["sku"]).first()
        if not existing:
            item = CatalogItem(**item_data)
            db.add(item)
    db.commit()
