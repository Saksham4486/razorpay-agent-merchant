import os
import asyncio
import logging
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.app.config import settings
from backend.app.database import engine, Base, SessionLocal
from backend.app.seed_data import seed_catalog
from backend.app.routes import (
    catalog,
    negotiate,
    checkout,
    orders,
    webhooks,
    audit,
    ads,
    chat,
    admin,
    acp
)
from backend.app.routes.orders import expire_order_if_due
from backend.app.models import Order
from backend.app.services.payment_service import payment_service

# Structured JSON Logger Setup (Phase 8)
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("main")

async def background_order_expiry_sweep():
    """
    Background sweep task (Phase 4 Task 3):
    Proactively checks for expired pending_payment orders every 60s,
    marks them as expired, and records audit trail entries.
    """
    while True:
        try:
            await asyncio.sleep(60)
            db = SessionLocal()
            try:
                pending_orders = db.query(Order).filter(Order.status == "pending_payment").all()
                expired_count = 0
                for ord_entry in pending_orders:
                    if expire_order_if_due(ord_entry, db):
                        expired_count += 1
                if expired_count > 0:
                    db.commit()
                    logger.info(f"Background sweep expired {expired_count} pending order(s).")
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error during background order expiry sweep: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB schema
    logger.info("Initializing database schema...")
    Base.metadata.create_all(bind=engine)
    
    # Seed initial SKUs
    db = SessionLocal()
    try:
        seed_catalog(db)
        logger.info("Catalog SKUs successfully seeded.")
    finally:
        db.close()

    # Start background order expiry task
    sweep_task = asyncio.create_task(background_order_expiry_sweep())
    
    yield
    
    sweep_task.cancel()
    try:
        await sweep_task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Autonomous Agent Merchant System on Razorpay Test-Mode APIs (Hardened)",
    lifespan=lifespan
)

# Enable CORS for local development and integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(catalog.router)
app.include_router(negotiate.router)
app.include_router(checkout.router)
app.include_router(orders.router)
app.include_router(webhooks.router)
app.include_router(webhooks.webhook_alias_router)
app.include_router(audit.router)
app.include_router(ads.router)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(acp.router)

# Mount Static UI Files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def read_root():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Razorpay Agent Merchant System is running. See /docs for API schema."}

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "is_mock": payment_service.is_mock,
        "mode": "mock_sandbox" if payment_service.is_mock else "live_test_mode"
    }
