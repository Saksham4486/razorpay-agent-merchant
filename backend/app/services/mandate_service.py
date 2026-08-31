import hmac
import hashlib
import datetime
from typing import Tuple, Optional
from backend.app.schemas import BuyerMandate
from backend.app.config import settings

def verify_mandate_signature(mandate: BuyerMandate, signature: str) -> bool:
    """
    Verifies AP2-style buyer mandate HMAC signature.
    """
    if not signature:
        return False
    msg = f"{mandate.agent_id}|{mandate.sku}|{mandate.max_unit_price:.2f}|{mandate.max_discount_pct:.2f}|{mandate.max_quantity}|{mandate.valid_until.isoformat()}"
    expected = hmac.new(
        key=settings.AGENT_AUTH_SECRET.encode("utf-8"),
        msg=msg.encode("utf-8"),
        digestmod=hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

def sign_mandate(mandate: BuyerMandate) -> str:
    """
    Generates valid HMAC signature for an AP2 buyer mandate.
    """
    msg = f"{mandate.agent_id}|{mandate.sku}|{mandate.max_unit_price:.2f}|{mandate.max_discount_pct:.2f}|{mandate.max_quantity}|{mandate.valid_until.isoformat()}"
    return hmac.new(
        key=settings.AGENT_AUTH_SECRET.encode("utf-8"),
        msg=msg.encode("utf-8"),
        digestmod=hashlib.sha256
    ).hexdigest()

def evaluate_buyer_mandate(
    mandate: Optional[BuyerMandate],
    signature: Optional[str],
    sku: str,
    quantity: int,
    requested_discount_pct: float
) -> Tuple[bool, str]:
    """
    Evaluates buyer mandate bounds before merchant policy check.
    Returns (is_allowed, reason_string).
    """
    if not mandate:
        return True, "No buyer mandate attached."

    if not signature or not verify_mandate_signature(mandate, signature):
        return False, "🚫 AP2 Mandate Signature Verification Failed: Cryptographic signature mismatch."

    now = datetime.datetime.now(datetime.timezone.utc)
    mandate_exp = mandate.valid_until.replace(tzinfo=datetime.timezone.utc) if mandate.valid_until.tzinfo is None else mandate.valid_until
    
    if now > mandate_exp:
        return False, f"⌛ AP2 Mandate Expired: Mandate expired at {mandate.valid_until.isoformat()}."

    if mandate.sku != sku:
        return False, f"🚫 AP2 Mandate SKU Mismatch: Mandate is for '{mandate.sku}', requested '{sku}'."

    if quantity > mandate.max_quantity:
        return False, f"🚫 AP2 Mandate Violation: Requested quantity ({quantity}) exceeds buyer authorized mandate limit ({mandate.max_quantity})."

    if requested_discount_pct > mandate.max_discount_pct:
        return False, f"🚫 AP2 Mandate Violation: Requested discount ({requested_discount_pct:.1f}%) exceeds buyer mandate cap ({mandate.max_discount_pct:.1f}%)."

    return True, f"✅ AP2 Buyer Mandate Verified: Authorized by buyer agent {mandate.agent_id}."
