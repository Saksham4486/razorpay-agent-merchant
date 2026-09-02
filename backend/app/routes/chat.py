import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models import CatalogItem
from backend.app.schemas import (
    ChatRequest, ChatResponse, ToolCallLog,
    NegotiateRequest, CheckoutRequest
)
from backend.app.routes.negotiate import negotiate_price
from backend.app.routes.checkout import create_checkout
from backend.app.services.llm_service import llm_service
from backend.app.services.upsell_service import evaluate_upsell_offer
from backend.app.config import settings

router = APIRouter(prefix="/api/chat", tags=["Conversational Checkout"])

@router.post("", response_model=ChatResponse)
def handle_chat_message(req: ChatRequest, db: Session = Depends(get_db)):
    """
    Multilingual Conversational Checkout Agent.
    Parses intent via LLM tool calling, executes policy engine tools, and replies natively.
    """
    catalog_items = db.query(CatalogItem).all()

    if not req.messages:
        lang = req.language if req.language != "auto" else "en"
        first_item = catalog_items[0] if catalog_items else None
        welcome_reply = llm_service.format_multilingual_response(
            lang=lang,
            message_type="catalog",
            params={
                "name": first_item.name if first_item else "Product",
                "sku": first_item.sku if first_item else "",
                "price": first_item.price_inr if first_item else 0.0,
                "max_discount": first_item.max_discount_pct if first_item else 15.0
            }
        )
        return ChatResponse(
            reply=welcome_reply,
            language=lang,
            razorpay_key_id=settings.RAZORPAY_KEY_ID
        )

    last_user_msg = req.messages[-1].content
    
    # 1. Detect language from message or explicit request
    detected_lang = llm_service.detect_language(
        text=last_user_msg,
        hint_lang=req.language if req.language != "auto" else None
    )
    
    # 2. Parse intent via LLM tool-calling parser
    parsed = llm_service.parse_chat_intent_with_llm(last_user_msg, catalog_items, lang=detected_lang)
    matched_sku = parsed.get("sku")
    intent = parsed.get("intent", "info")
    requested_discount = float(parsed.get("requested_discount") or 0.0)
    quantity = int(parsed.get("quantity") or 1)

    tool_logs = []
    active_order = None
    upsell_offer = None
    reply_text = ""

    # If general catalog request or no SKU matched yet
    if intent == "catalog" or not matched_sku:
        first_item = catalog_items[0] if catalog_items else None
        reply_text = llm_service.format_multilingual_response(
            lang=detected_lang,
            message_type="catalog",
            params={
                "name": first_item.name if first_item else "Enterprise Gateway",
                "sku": first_item.sku if first_item else "SKU-AI-ROUTER-PRO",
                "price": first_item.price_inr if first_item else 45000.0,
                "max_discount": first_item.max_discount_pct if first_item else 15.0
            }
        )
        return ChatResponse(
            reply=reply_text,
            language=detected_lang,
            tool_calls=[],
            razorpay_key_id=settings.RAZORPAY_KEY_ID
        )

    item = db.query(CatalogItem).filter(CatalogItem.sku == matched_sku).first()
    if not item:
        item = catalog_items[0]

    # 3. Negotiate Intent
    if intent == "negotiate" or (intent != "checkout" and requested_discount > 0):
        neg_req = NegotiateRequest(
            sku=item.sku,
            requested_discount_pct=requested_discount,
            quantity=quantity,
            agent_id=None,
            actor_type="human"
        )
        neg_res = negotiate_price(neg_req, db=db)
        
        tool_logs.append(ToolCallLog(
            tool_name="api_negotiate",
            arguments={"sku": item.sku, "requested_discount_pct": requested_discount, "quantity": quantity},
            result=neg_res.model_dump()
        ))

        msg_type = "negotiate_approved" if neg_res.allowed else "negotiate_rejected"
        reply_text = llm_service.format_multilingual_response(
            lang=detected_lang,
            message_type=msg_type,
            params={
                "name": item.name,
                "sku": item.sku,
                "price": item.price_inr,
                "original_price": neg_res.original_price_inr,
                "requested_discount": requested_discount,
                "max_discount": item.max_discount_pct,
                "final_unit_price": neg_res.final_unit_price_inr,
                "total_order_value": neg_res.total_order_value_inr,
                "quantity": quantity,
                "reason": neg_res.reason
            }
        )

        upsell_offer = None
        if neg_res.allowed:
            upsell_offer = evaluate_upsell_offer(
                triggering_sku=item.sku, db=db, agent_id=None, actor="chat_human"
            )
            if upsell_offer:
                reply_text += (
                    f"\n\n💡 **You might also like:** {upsell_offer['name']} "
                    f"(`{upsell_offer['sku']}`) - ₹{upsell_offer['final_unit_price_inr']:,.2f} "
                    f"({upsell_offer['offered_discount_pct']}% off). Want to add it?"
                )

        return ChatResponse(
            reply=reply_text,
            language=detected_lang,
            tool_calls=tool_logs,
            razorpay_key_id=settings.RAZORPAY_KEY_ID,
            upsell_offer=upsell_offer
        )

    # 4. Checkout Intent
    checkout_confirmations = [
        "checkout", "buy", "pay", "order",
        "yes", "confirm", "ok", "haan", "sahi hai",
        "हाँ", "खरीदना", "पे", "भुगतान",
        "ஆம்", "வாங்க", "செலுத்து",
        "అవును", "కొంటాను", "చెల్లింపు",
        "si", "comprar", "pagar", "de acuerdo"
    ]
    if intent == "checkout" or any(w in last_user_msg.lower() for w in checkout_confirmations):
        discount_to_use = min(requested_discount, item.max_discount_pct) if requested_discount > 0 else 0.0
        idempotency_key = f"chat_user_{uuid.uuid4().hex[:12]}"
        
        checkout_req = CheckoutRequest(
            sku=item.sku,
            quantity=quantity,
            requested_discount_pct=discount_to_use,
            actor_type="human",
            idempotency_key=idempotency_key,
            customer_name="Human Shopper via Multilingual Chat"
        )
        
        try:
            order_res = create_checkout(checkout_req, db=db)
            tool_logs.append(ToolCallLog(
                tool_name="api_checkout",
                arguments={"sku": item.sku, "quantity": quantity, "discount_pct": discount_to_use, "idempotency_key": idempotency_key},
                result=order_res.model_dump()
            ))
            active_order = order_res

            upsell_offer = None
            if order_res.status in ("paid", "pending_payment"):
                upsell_offer = evaluate_upsell_offer(
                    triggering_sku=item.sku, db=db, agent_id=None, actor="chat_human"
                )

            if order_res.status == "pending_approval":
                reply_text = llm_service.format_multilingual_response(
                    lang=detected_lang,
                    message_type="pending_approval",
                    params={
                        "name": item.name,
                        "sku": item.sku,
                        "quantity": quantity,
                        "total_order_value": order_res.total_amount_inr,
                        "order_reference": order_res.order_reference
                    }
                )
            else:
                reply_text = llm_service.format_multilingual_response(
                    lang=detected_lang,
                    message_type="checkout_ready",
                    params={
                        "name": item.name,
                        "sku": item.sku,
                        "quantity": quantity,
                        "total_order_value": order_res.total_amount_inr,
                        "order_reference": order_res.order_reference,
                        "razorpay_order_id": order_res.razorpay_order_id,
                        "status": order_res.status
                    }
                )
                if upsell_offer:
                    reply_text += (
                        f"\n\n💡 **Complete your setup:** {upsell_offer['name']} "
                        f"(`{upsell_offer['sku']}`) - ₹{upsell_offer['final_unit_price_inr']:,.2f} "
                        f"({upsell_offer['offered_discount_pct']}% off). Want to add it to a new order?"
                    )
        except HTTPException as e:
            reply_text = f"Checkout failed: {e.detail}"

        return ChatResponse(
            reply=reply_text,
            language=detected_lang,
            tool_calls=tool_logs,
            active_order=active_order,
            razorpay_key_id=settings.RAZORPAY_KEY_ID,
            upsell_offer=upsell_offer
        )

    # 5. Info Response
    reply_text = (
        f"**{item.name}** (`{item.sku}`)\n"
        f"• Price: ₹{item.price_inr:,.2f} / unit\n"
        f"• Description: {item.description}\n"
        f"• Max Discount Cap: {item.max_discount_pct}%\n\n"
        f"Would you like to negotiate a discount or proceed to checkout?"
    )
    return ChatResponse(
        reply=reply_text,
        language=detected_lang,
        tool_calls=[],
        razorpay_key_id=settings.RAZORPAY_KEY_ID
    )
