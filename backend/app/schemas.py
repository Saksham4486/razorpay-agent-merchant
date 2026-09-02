import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

# --- Catalog Schemas ---
class CatalogItemPolicy(BaseModel):
    min_order_inr: float
    requires_approval_above_inr: float
    max_discount_pct: float

class CatalogItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku: str
    name: str
    description: str
    category: str
    price_inr: float
    stock: int
    max_discount_pct: float
    currency: str = "INR"
    policy: CatalogItemPolicy
    image_url: Optional[str] = None

class CatalogResponse(BaseModel):
    items: List[CatalogItemSchema]
    count: int
    merchant_daily_cap_inr: float

# --- AP2 Signed Mandate Schema ---
class BuyerMandate(BaseModel):
    agent_id: str
    sku: str
    max_unit_price: float
    max_discount_pct: float
    max_quantity: int
    valid_until: datetime.datetime
    issued_at: datetime.datetime

# --- Negotiation Schemas ---
class NegotiateRequest(BaseModel):
    sku: str
    requested_discount_pct: float = Field(..., ge=0.0, le=100.0, description="Discount percentage requested by buyer")
    quantity: int = Field(default=1, ge=1)
    agent_id: Optional[str] = Field(default=None, description="Identifier for AI buyer agent if applicable")
    actor_type: str = Field(default="human", description="'human' or 'ai_agent'")
    mandate: Optional[BuyerMandate] = None
    mandate_signature: Optional[str] = None

class NegotiateResponse(BaseModel):
    sku: str
    original_price_inr: float
    requested_discount_pct: float
    approved_discount_pct: float
    final_unit_price_inr: float
    total_order_value_inr: float
    policy_status: str  # "approved", "rejected", "pending_approval"
    allowed: bool
    reason: str  # Human-readable explainable reason string
    requires_approval: bool = False
    agent_trust_score: Optional[float] = None
    effective_approval_threshold_inr: float
    mandate_verified: Optional[bool] = None
    issued_agent_key: Optional[str] = Field(
        default=None,
        description="Raw agent key, present only on the FIRST request for a brand-new agent_id. Store it; it cannot be retrieved again."
    )

# --- Checkout Schemas ---
class CheckoutRequest(BaseModel):
    sku: str
    quantity: int = Field(default=1, ge=1)
    requested_discount_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    actor_type: str = Field(default="human", description="'human' or 'ai_agent'")
    agent_id: Optional[str] = Field(default=None, description="Required or optional agent identifier")
    idempotency_key: str = Field(..., min_length=8, description="Client-generated unique idempotency key")
    customer_name: Optional[str] = "Valued Customer"
    customer_email: Optional[str] = "buyer@example.com"
    customer_phone: Optional[str] = "+919876543210"
    ttl_minutes: Optional[int] = Field(default=15, ge=1, le=120, description="Time to pay before link expires")
    mandate: Optional[BuyerMandate] = None
    mandate_signature: Optional[str] = None

class CheckoutResponse(BaseModel):
    order_reference: str
    sku: str
    quantity: int
    unit_price_inr: float
    discount_pct: float
    total_amount_inr: float
    status: str  # "pending_payment", "pending_approval", "paid", "rejected", "expired", "refunded"
    razorpay_order_id: Optional[str] = None
    razorpay_key_id: Optional[str] = None
    idempotent_replay: bool = False
    policy_reason: str
    expires_at: Optional[datetime.datetime] = None
    is_link_active: bool = True
    created_at: datetime.datetime
    issued_agent_key: Optional[str] = Field(
        default=None,
        description="Raw agent key, present only on the FIRST request for a brand-new agent_id. Store it; it cannot be retrieved again."
    )

# --- Payment Verification Schema (Signature is strictly REQUIRED) ---
class VerifyPaymentRequest(BaseModel):
    razorpay_payment_id: str = Field(..., min_length=4, description="Payment ID returned by Razorpay Checkout")
    razorpay_order_id: str = Field(..., min_length=4, description="Order ID returned by Razorpay Checkout")
    razorpay_signature: str = Field(..., min_length=8, description="Cryptographic HMAC SHA256 signature from Razorpay")

# --- Refund Schemas ---
class RefundRequest(BaseModel):
    amount_inr: Optional[float] = None
    reason: Optional[str] = "Customer requested refund"

class RefundResponse(BaseModel):
    order_reference: str
    refund_id: str
    amount_inr: float
    status: str  # "refunded"
    message: str

# --- Fallback Polling Response ---
class FallbackPollResponse(BaseModel):
    order_reference: str
    razorpay_order_id: Optional[str]
    previous_status: str
    current_status: str
    resolved_via: str
    payment_id: Optional[str] = None
    message: str

# --- Audit Log Schemas ---
class AuditLogSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime.datetime
    actor: str
    agent_id: Optional[str]
    sku: str
    requested_discount: float
    order_value_inr: float
    policy_decision: str
    reason: str
    razorpay_order_id: Optional[str]
    status: str
    failure_detail: Optional[str]
    metadata_json: Optional[str]
    prev_hash: Optional[str] = None
    entry_hash: Optional[str] = None

class AgentTrustScoreSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_id: str
    total_orders: int
    paid_orders: int
    failed_orders: int
    rejected_orders: int
    trust_score: float
    last_updated: datetime.datetime

class AuditDashboardResponse(BaseModel):
    logs: List[AuditLogSchema]
    total_logs: int
    trust_scores: List[AgentTrustScoreSchema]
    daily_spend_inr: float
    daily_cap_inr: float
    chain_intact: bool = True

# --- Agent Key Registration Schemas ---
class AgentRegisterRequest(BaseModel):
    agent_id: str = Field(..., min_length=3, max_length=100)

class AgentRegisterResponse(BaseModel):
    agent_id: str
    api_key: str
    message: str

# --- ACP (Agentic Commerce Protocol) Schemas ---
class AcpProductItem(BaseModel):
    id: str
    title: str
    description: str
    price: float
    currency: str = "INR"
    availability: str = "in_stock"
    max_discount_pct: float
    requires_approval_above: float

class AcpFeedResponse(BaseModel):
    protocol: str = "ACP-1.0-draft"
    merchant_name: str
    feed_timestamp: datetime.datetime
    items: List[AcpProductItem]

class AcpCheckoutSessionCreate(BaseModel):
    sku: str
    quantity: int = 1
    requested_discount_pct: float = 0.0
    agent_id: Optional[str] = None
    mandate: Optional[BuyerMandate] = None
    mandate_signature: Optional[str] = None

class AcpCheckoutSessionUpdate(BaseModel):
    quantity: Optional[int] = None
    requested_discount_pct: Optional[float] = None

class AcpCheckoutSessionResponse(BaseModel):
    session_id: str
    status: str  # "open", "completed", "cancelled", "expired"
    sku: str
    quantity: int
    unit_price_inr: float
    total_amount_inr: float
    policy_status: str
    policy_reason: str
    razorpay_order_id: Optional[str] = None
    razorpay_key_id: Optional[str] = None
    expires_at: datetime.datetime

# --- Multilingual Ad Generation Schemas ---
class AdGenerateRequest(BaseModel):
    sku: str
    languages: Optional[List[str]] = ["en", "hi", "ta", "te", "es"]
    target_audience: Optional[str] = "Tech enthusiasts & enterprise buyers"

class MultilingualAdItem(BaseModel):
    language_code: str
    language_name: str
    headline: str
    body_text: str
    call_to_action: str
    hashtags: List[str]
    discount_hook: str
    chat_deep_link: str
    generated_by: str = Field(default="template_fallback", description="'gemini' or 'template_fallback'")

class AdGenerateResponse(BaseModel):
    sku: str
    product_name: str
    campaign_name: str
    ads: List[MultilingualAdItem]

# --- Conversational Chat Schemas ---
class ChatMessage(BaseModel):
    role: str
    content: str

class ToolCallLog(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]
    result: Dict[str, Any]

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    agent_id: Optional[str] = "human_shopper"
    language: Optional[str] = "auto"

class ChatResponse(BaseModel):
    reply: str
    language: str = "en"
    tool_calls: List[ToolCallLog] = []
    active_order: Optional[CheckoutResponse] = None
    razorpay_key_id: Optional[str] = None

# --- Agent Identity Schemas (A1) ---
class AgentRegisterRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100, description="Unique identifier the agent wants to operate under")

class AgentRegisterResponse(BaseModel):
    agent_id: str
    agent_key: str = Field(..., description="Raw secret key. Shown ONCE. Send it as the X-Agent-Key header on every subsequent request for this agent_id.")

# --- AP2 Mandate Issuance Schema (A4) ---
class MandateIssueRequest(BaseModel):
    sku: str
    max_unit_price: float = Field(..., gt=0)
    max_discount_pct: float = Field(..., ge=0.0, le=100.0)
    max_quantity: int = Field(..., ge=1)
    valid_minutes: int = Field(default=60, ge=1, le=1440, description="Mandate validity window in minutes")

class MandateIssueResponse(BaseModel):
    mandate: BuyerMandate
    mandate_signature: str
