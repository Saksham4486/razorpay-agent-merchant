import datetime
import hashlib
import json
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from backend.app.database import Base

def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)

class CatalogItem(Base):
    __tablename__ = "catalog_items"

    sku = Column(String(50), primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(100), default="General")
    price_inr = Column(Float, nullable=False)
    stock = Column(Integer, default=100)
    max_discount_pct = Column(Float, default=15.0)
    currency = Column(String(10), default="INR")
    min_order_inr = Column(Float, default=0.0)
    requires_approval_above_inr = Column(Float, default=50000.0)
    image_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=utcnow)

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_reference = Column(String(64), unique=True, index=True, nullable=False)
    actor = Column(String(100), nullable=False)  # 'ad_human' or 'ai_agent:<agent_id>'
    agent_id = Column(String(100), nullable=True, index=True)
    sku = Column(String(50), ForeignKey("catalog_items.sku"), nullable=False)
    quantity = Column(Integer, default=1)
    unit_price_inr = Column(Float, nullable=False)
    requested_discount_pct = Column(Float, default=0.0)
    approved_discount_pct = Column(Float, default=0.0)
    total_amount_inr = Column(Float, nullable=False)
    
    # State machine: pending_approval, pending_payment, pending_confirmation, paid, failed, rejected, expired, refunded
    status = Column(String(50), default="pending_payment", index=True)
    
    razorpay_order_id = Column(String(100), nullable=True, index=True)
    razorpay_payment_id = Column(String(100), nullable=True)
    idempotency_key = Column(String(128), unique=True, index=True, nullable=False)
    policy_reason = Column(Text, nullable=False)
    
    # Time-to-Pay (TTL) and Single-Use Link Deadening
    expires_at = Column(DateTime, nullable=True)
    is_link_active = Column(Boolean, default=True)
    
    # Refunds
    refund_id = Column(String(100), nullable=True)
    refund_amount_inr = Column(Float, nullable=True)
    
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    
    # Relationships
    catalog_item = relationship("CatalogItem")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=utcnow, index=True)
    actor = Column(String(100), nullable=False)
    agent_id = Column(String(100), nullable=True, index=True)
    sku = Column(String(50), nullable=False)
    requested_discount = Column(Float, default=0.0)
    order_value_inr = Column(Float, nullable=False)
    policy_decision = Column(String(50), nullable=False)
    reason = Column(Text, nullable=False)
    razorpay_order_id = Column(String(100), nullable=True, index=True)
    status = Column(String(50), nullable=False)
    failure_detail = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    
    # Cryptographic Tamper-Evident Hash Chaining
    prev_hash = Column(String(64), nullable=True)
    entry_hash = Column(String(64), nullable=True, index=True)

    def compute_hash(self, prev_h: str = "") -> str:
        prev = prev_h if prev_h else (self.prev_hash or "0" * 64)
        data = f"{prev}|{self.actor}|{self.sku}|{self.order_value_inr:.2f}|{self.policy_decision}|{self.reason}|{self.status}"
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

class AgentTrustScore(Base):
    __tablename__ = "agent_trust_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(100), unique=True, index=True, nullable=False)
    total_orders = Column(Integer, default=0)
    paid_orders = Column(Integer, default=0)
    failed_orders = Column(Integer, default=0)
    rejected_orders = Column(Integer, default=0)
    trust_score = Column(Float, default=0.5)
    agent_key_hash = Column(String(128), nullable=True)
    last_updated = Column(DateTime, default=utcnow, onupdate=utcnow)

class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    idempotency_key = Column(String(128), primary_key=True, index=True)
    actor = Column(String(100), nullable=False)
    request_hash = Column(String(128), nullable=False)
    order_reference = Column(String(64), nullable=False)
    response_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)

class ProcessedWebhookEvent(Base):
    __tablename__ = "processed_webhook_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(128), unique=True, index=True, nullable=False)
    event_type = Column(String(100), nullable=False)
    payload_hash = Column(String(128), nullable=True)
    processed_at = Column(DateTime, default=utcnow)
