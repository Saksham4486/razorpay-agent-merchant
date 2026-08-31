import uuid
import datetime
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models import Order, utcnow
from backend.app.services.payment_service import payment_service

client = TestClient(app)

def test_signature_verification_and_dead_payment_links():
    sku = "SKU-CLOUD-CREDITS"
    idemp_key = f"sig_test_{uuid.uuid4().hex}"

    # 1. Initiate Checkout
    chk_res = client.post("/api/checkout", json={
        "sku": sku,
        "quantity": 1,
        "requested_discount_pct": 5.0,
        "actor_type": "human",
        "idempotency_key": idemp_key
    })
    assert chk_res.status_code == 200
    chk = chk_res.json()
    order_ref = chk["order_reference"]
    rzp_order_id = chk["razorpay_order_id"]

    # 2. Forged Signature Attempt -> MUST BE REJECTED with 400
    fake_payment_id = f"pay_forged_{uuid.uuid4().hex[:8]}"
    bad_v = client.post(f"/api/orders/{order_ref}/verify-payment", json={
        "razorpay_payment_id": fake_payment_id,
        "razorpay_order_id": rzp_order_id,
        "razorpay_signature": "invalid_forged_hmac_signature_value"
    })
    assert bad_v.status_code == 400
    assert bad_v.json()["detail"]["error"] == "InvalidPaymentSignature"

    # 3. Genuine HMAC SHA256 Signature -> MUST SUCCEED
    valid_payment_id = f"pay_valid_{uuid.uuid4().hex[:8]}"
    valid_sig = payment_service.generate_test_payment_signature(rzp_order_id, valid_payment_id)

    good_v = client.post(f"/api/orders/{order_ref}/verify-payment", json={
        "razorpay_payment_id": valid_payment_id,
        "razorpay_order_id": rzp_order_id,
        "razorpay_signature": valid_sig
    })
    assert good_v.status_code == 200
    assert good_v.json()["status"] == "paid"
    assert good_v.json()["is_link_active"] is False

    # 4. Repeat Payment Attempt on the DEAD link -> MUST BE REJECTED with 400
    repeat_v = client.post(f"/api/orders/{order_ref}/verify-payment", json={
        "razorpay_payment_id": f"pay_repeat_{uuid.uuid4().hex[:8]}",
        "razorpay_order_id": rzp_order_id,
        "razorpay_signature": valid_sig
    })
    assert repeat_v.status_code == 400
    assert repeat_v.json()["detail"]["error"] == "DeadPaymentLink"

def test_refund_lifecycle():
    sku = "SKU-POS-TERMINAL"
    idemp_key = f"refund_test_{uuid.uuid4().hex}"

    # 1. Checkout & Pay
    chk = client.post("/api/checkout", json={
        "sku": sku,
        "quantity": 1,
        "requested_discount_pct": 0.0,
        "actor_type": "human",
        "idempotency_key": idemp_key
    }).json()
    order_ref = chk["order_reference"]
    rzp_order_id = chk["razorpay_order_id"]
    
    pay_id = f"pay_rfnd_{uuid.uuid4().hex[:8]}"
    sig = payment_service.generate_test_payment_signature(rzp_order_id, pay_id)
    
    client.post(f"/api/orders/{order_ref}/verify-payment", json={
        "razorpay_payment_id": pay_id,
        "razorpay_order_id": rzp_order_id,
        "razorpay_signature": sig
    })

    # 2. Execute Refund
    ref_res = client.post(f"/api/orders/{order_ref}/refund", json={
        "reason": "Customer cancellation request"
    })
    assert ref_res.status_code == 200
    ref_data = ref_res.json()
    assert ref_data["status"] == "refunded"
    assert ref_data["refund_id"] is not None

    # 3. Verify in order query
    order_q = client.get(f"/api/orders/{order_ref}").json()
    assert order_q["status"] == "refunded"
    assert order_q["refund_id"] == ref_data["refund_id"]
