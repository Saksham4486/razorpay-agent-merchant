import re
import json
import logging
from typing import List, Dict, Any, Optional
from backend.app.config import settings
from backend.app.models import CatalogItem

logger = logging.getLogger("llm_service")

# Multilingual Ad Templates & Generators
AD_TEMPLATES = {
    "en": {
        "name": "English",
        "headline": "🚀 Supercharge Your Operations with {name}!",
        "body": "Get enterprise-grade performance for just ₹{price:,.2f}. Limited stock available ({stock} units remaining). Exclusive instant checkout discounts available!",
        "cta": "Negotiate & Buy Now",
        "hashtags": ["#TechDeals", "#Enterprise", "#RazorpayCheckout"],
        "hook": "Special agent-negotiated discount available!"
    },
    "hi": {
        "name": "Hindi (हिंदी)",
        "headline": "🚀 {name} के साथ अपने बिजनेस को नई ऊंचाइयों पर ले जाएं!",
        "body": "पाएं बेहतरीन परफॉर्मेंस सिर्फ ₹{price:,.2f} में। केवल {stock} यूनिट्स शेष। तुरंत चैट करें और सबसे बेहतरीन डिस्काउंट पाएं!",
        "cta": "अभी मोलभाव करें और खरीदें",
        "hashtags": ["#स्मार्ट_व्यापार", "#ऑफर", "#रेज़रपे"],
        "hook": "सीमित समय के लिए विशेष छूट उपलब्ध!"
    },
    "ta": {
        "name": "Tamil (தமிழ்)",
        "headline": "🚀 {name} உடன் உங்கள் வணிகத்தை அடுத்த கட்டத்திற்கு கொண்டு செல்லுங்கள்!",
        "body": "உயர் செயல்திறன் வெறும் ₹{price:,.2f} விலையில். {stock} அலகுகள் மட்டுமே உள்ளன. சிறந்த தள்ளுபடியுடன் வாங்க உரையாடுங்கள்!",
        "cta": "பேசி உடனே வாங்கவும்",
        "hashtags": ["#வணிகம்", "#தள்ளுபடி", "#Razorpay"],
        "hook": "சிறந்த தள்ளுபடி சலுகை கிடைக்கிறது!"
    },
    "te": {
        "name": "Telugu (తెలుగు)",
        "headline": "🚀 {name} తో మీ వ్యాపార సామర్థ్యాన్ని పెంచుకోండి!",
        "body": "అద్భుతమైన పనితీరు కేవలం ₹{price:,.2f} లో. {stock} యూనిట్లు మాత్రమే మిగిలి ఉన్నాయి. బెస్ట్ డిస్కౌంట్ కోసం ఇప్పుడే చాట్ చేయండి!",
        "cta": "బేరమాడి వెంటనే కొనండి",
        "hashtags": ["#వ్యాపార_ఆఫర్", "#డిస్కౌంట్", "#Razorpay"],
        "hook": "ప్రత్యేకమైన ఇన్స్టంట్ డిస్కౌంట్ ఆఫర్!"
    },
    "es": {
        "name": "Spanish (Español)",
        "headline": "🚀 ¡Potencia tu negocio con {name}!",
        "body": "Rendimiento de nivel empresarial por solo ₹{price:,.2f}. Quedan {stock} unidades. ¡Negocia tu descuento instantáneo en el chat!",
        "cta": "Negociar y Comprar Ahora",
        "hashtags": ["#OfertasTech", "#Empresas", "#Razorpay"],
        "hook": "¡Descuento negociado exclusivo disponible!"
    }
}

class LLMService:
    def __init__(self):
        self.gemini_key = settings.GEMINI_API_KEY
        self.anthropic_key = settings.ANTHROPIC_API_KEY
        self.has_llm = bool(self.gemini_key or self.anthropic_key)

    def detect_language(self, text: str, hint_lang: Optional[str] = None) -> str:
        """
        Detects conversation language from scripts, words, or explicit hints.
        Supports: 'en', 'hi', 'ta', 'te', 'es'
        """
        if hint_lang and hint_lang in ["hi", "ta", "te", "es", "en"]:
            return hint_lang

        if re.search(r'[\u0900-\u097F]', text):
            return "hi"  # Devanagari
        if re.search(r'[\u0B80-\u0BFF]', text):
            return "ta"  # Tamil
        if re.search(r'[\u0C00-\u0C7F]', text):
            return "te"  # Telugu

        text_lower = text.lower()
        if any(w in text_lower for w in ["hindi", "हिंदी", "hinglish", "hindi me"]):
            return "hi"
        if any(w in text_lower for w in ["tamil", "தமிழ்", "tamizh"]):
            return "ta"
        if any(w in text_lower for w in ["telugu", "తెలుగు"]):
            return "te"
        if any(w in text_lower for w in ["spanish", "español", "espanol", "hola", "buenos", "gracias"]):
            return "es"
        if any(w in text_lower for w in ["descuento", "comprar", "cuanto", "precio", "quiero", "pagar", "por favor"]):
            return "es"
        if any(w in text_lower for w in ["chahiye", "kitna", "khareedna", "kharidna", "batao", "kardo", "kam karo", "discount do"]):
            return "hi"

        return "en"

    def generate_multilingual_ads(
        self,
        item: CatalogItem,
        languages: Optional[List[str]] = None,
        target_audience: Optional[str] = "Tech enthusiasts & enterprise buyers"
    ) -> List[Dict[str, Any]]:
        """
        Generates real, LLM-authored multilingual ad copy per language via
        Gemini (Section C) - same google-genai pattern as
        parse_chat_intent_with_llm(). Falls back to the static AD_TEMPLATES
        only when no GEMINI_API_KEY is configured, or if a given language's
        LLM call fails, so the endpoint always returns a complete result.
        """
        selected_langs = languages or ["en", "hi", "ta", "te", "es"]
        ads = []

        for lang in selected_langs:
            ad = None
            if self.gemini_key:
                ad = self._generate_ad_via_gemini(item, lang, target_audience)
            if ad is None:
                ad = self._generate_ad_from_template(item, lang)
            ads.append(ad)

        return ads

    def _generate_ad_from_template(self, item: CatalogItem, lang: str) -> Dict[str, Any]:
        template = AD_TEMPLATES.get(lang, AD_TEMPLATES["en"])
        headline = template["headline"].format(name=item.name, price=item.price_inr, stock=item.stock)
        body = template["body"].format(name=item.name, price=item.price_inr, stock=item.stock)
        return {
            "language_code": lang,
            "language_name": template["name"],
            "headline": headline,
            "body_text": body,
            "call_to_action": template["cta"],
            "hashtags": template["hashtags"],
            "discount_hook": template["hook"],
            "chat_deep_link": f"/#chat?sku={item.sku}&lang={lang}",
            "generated_by": "template_fallback"
        }

    def _generate_ad_via_gemini(
        self,
        item: CatalogItem,
        lang: str,
        target_audience: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.gemini_key)
            lang_names = {"en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu", "es": "Spanish"}
            lang_name = lang_names.get(lang, lang)

            prompt = (
                f"Write short, punchy advertising copy in {lang_name} for this product, "
                f"targeting: {target_audience}.\n"
                f"Product: {item.name}\n"
                f"Description: {item.description}\n"
                f"Price: INR {item.price_inr:,.2f}\n"
                f"Stock remaining: {item.stock} units\n"
                f"Respond as valid JSON with EXACTLY these keys:\n"
                f'{{"headline": "<short punchy headline, may include an emoji>", '
                f'"body_text": "<1-2 sentence ad body mentioning the price>", '
                f'"call_to_action": "<short CTA button text>", '
                f'"hashtags": ["<3 short hashtags relevant to this product, no # needed>"], '
                f'"discount_hook": "<one short line teasing a negotiable/instant discount>"}}\n'
                f"All text values must be written in {lang_name}, not English (except for 'en')."
            )

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            parsed = json.loads(response.text)

            return {
                "language_code": lang,
                "language_name": lang_name,
                "headline": parsed["headline"],
                "body_text": parsed["body_text"],
                "call_to_action": parsed["call_to_action"],
                "hashtags": parsed.get("hashtags", []),
                "discount_hook": parsed.get("discount_hook", ""),
                "chat_deep_link": f"/#chat?sku={item.sku}&lang={lang}",
                "generated_by": "gemini"
            }
        except Exception as e:
            logger.warning(f"Gemini ad generation failed for lang={lang}: {e}. Falling back to template.")
            return None

    def parse_chat_intent_with_llm(
        self,
        user_message: str,
        catalog_items: List[CatalogItem],
        lang: str = "en"
    ) -> Dict[str, Any]:
        """
        Tool-calling LLM intent parser (Phase 5):
        Calls Gemini / Anthropic if available, else falls back to robust regex matching.
        The LLM only classifies the intent and extracts arguments.
        It NEVER computes financial decisions or discounts itself.
        """
        # Try real Gemini LLM if key is present
        if self.gemini_key:
            try:
                from google import genai
                from google.genai import types
                
                client = genai.Client(api_key=self.gemini_key)
                skus = [f"{item.sku} ({item.name}, Price: INR {item.price_inr})" for item in catalog_items]
                
                prompt = (
                    f"You are a sales routing assistant for an enterprise store.\n"
                    f"Catalog SKUs: {', '.join(skus)}\n"
                    f"User message: '{user_message}'\n"
                    f"Task: Extract the tool to invoke and parameters as valid JSON:\n"
                    f'{{"intent": "negotiate" | "checkout" | "catalog" | "info", "sku": "<matching SKU>", "requested_discount": <float>, "quantity": <int>}}'
                )
                
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                parsed = json.loads(response.text)
                parsed["language"] = lang
                return parsed
            except Exception as e:
                logger.warning(f"LLM tool extraction failed: {e}. Using deterministic fallback parser.")

        # Deterministic regex parser fallback
        return self._fallback_parse_intent(user_message, catalog_items, lang)

    def _fallback_parse_intent(self, user_message: str, catalog_items: List[CatalogItem], lang: str) -> Dict[str, Any]:
        msg_lower = user_message.lower()
        
        matched_sku = None
        for item in catalog_items:
            if item.sku.lower() in msg_lower or any(word in msg_lower for word in item.name.lower().split() if len(word) > 3):
                matched_sku = item.sku
                break
        
        if not matched_sku and catalog_items:
            keywords = {
                "router": "SKU-AI-ROUTER-PRO", "राउटर": "SKU-AI-ROUTER-PRO", "ரவுட்டர்": "SKU-AI-ROUTER-PRO", "రౌటర్": "SKU-AI-ROUTER-PRO", "enrutador": "SKU-AI-ROUTER-PRO",
                "workstation": "SKU-GPU-DEV-BOX", "gpu": "SKU-GPU-DEV-BOX", "वर्कस्टेशन": "SKU-GPU-DEV-BOX", "ஒர்க்ஸ்டேஷன்": "SKU-GPU-DEV-BOX", "వర్క్‌స్టేషన్": "SKU-GPU-DEV-BOX", "estacion": "SKU-GPU-DEV-BOX",
                "pos": "SKU-POS-TERMINAL", "terminal": "SKU-POS-TERMINAL", "टर्मिनल": "SKU-POS-TERMINAL", "மெஷின்": "SKU-POS-TERMINAL", "టర్మినల్": "SKU-POS-TERMINAL",
                "credit": "SKU-CLOUD-CREDITS", "token": "SKU-CLOUD-CREDITS", "क्रेडिट": "SKU-CLOUD-CREDITS", "டோக்கன்": "SKU-CLOUD-CREDITS", "క్రెడిట్స్": "SKU-CLOUD-CREDITS", "creditos": "SKU-CLOUD-CREDITS",
                "desk": "SKU-ERGO-DESK", "डेस्क": "SKU-ERGO-DESK", "மேசை": "SKU-ERGO-DESK", "డెస్క్": "SKU-ERGO-DESK", "escritorio": "SKU-ERGO-DESK",
                "headset": "SKU-NOISE-HEADSET", "headphone": "SKU-NOISE-HEADSET", "हेडसेट": "SKU-NOISE-HEADSET", "ஹெட்செட்": "SKU-NOISE-HEADSET", "హెడ్‌సెట్": "SKU-NOISE-HEADSET", "auriculares": "SKU-NOISE-HEADSET"
            }
            for kw, sku in keywords.items():
                if kw in msg_lower:
                    matched_sku = sku
                    break

        discount_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:%|percent|pct|प्रतिशत|சதவீதம்|శాతం|por ciento)', msg_lower)
        requested_discount = float(discount_match.group(1)) if discount_match else 0.0
        
        qty_match = re.search(r'(\d+)\s*(?:units|qty|quantity|items|pieces|pcs|यूनिट|अंक|துண்டுகள்|యూనిట్లు|unidades)', msg_lower)
        quantity = int(qty_match.group(1)) if qty_match else 1
        
        checkout_triggers = [
            "buy", "checkout", "pay", "order", "purchase",
            "खरीदना", "पे", "ऑर्डर", "भुगतान", "खरीद", "लेना",
            "வாங்க", "செலுத்த", "ஆர்டர்", "வாங்கு",
            "కొనాలి", "చెల్లించు", "ఆర్డర్", "కొనుగోలు",
            "comprar", "pagar", "pedir", "orden", "finalizar"
        ]
        
        negotiate_triggers = [
            "discount", "deal", "negotiate", "offer", "less", "reduce", "price", "better on the price",
            "छूट", "डिस्काउंट", "कम", "ऑफर", "सस्ता", "मोलभाव", "कम करो",
            "தள்ளுபடி", "குறைக்க", "விலை", "பேசி", "சலுகை",
            "తగ్గింపు", "డిస్కౌంట్", "ధర", "బేరమాడి", "ఆఫర్",
            "descuento", "oferta", "negociar", "rebaja", "precio"
        ]

        catalog_triggers = [
            "list", "catalog", "products", "show me", "what do you sell",
            "कैटलॉग", "उत्पाद", "दिखाओ", "प्रोडक्ट्स",
            "பட்டியல்", "பொருட்கள்", "காட்டு",
            "కేటలాగ్", "ఉత్పత్తులు", "చూపించు",
            "catalogo", "productos", "mostrar"
        ]

        if any(w in msg_lower for w in checkout_triggers):
            intent = "checkout"
        elif any(w in msg_lower for w in negotiate_triggers) or requested_discount > 0:
            intent = "negotiate"
        elif any(w in msg_lower for w in catalog_triggers):
            intent = "catalog"
        else:
            intent = "info"
            
        return {
            "intent": intent,
            "sku": matched_sku,
            "requested_discount": requested_discount,
            "quantity": quantity,
            "language": lang
        }

    def format_multilingual_response(
        self,
        lang: str,
        message_type: str,
        params: Dict[str, Any]
    ) -> str:
        """
        Phrases structured policy results in natural language (English, Hindi, Tamil, Telugu, Spanish).
        """
        sku_name = params.get("name", "Product")
        sku_code = params.get("sku", "")
        price = params.get("price", 0.0)
        max_disc = params.get("max_discount", 15.0)
        req_disc = params.get("requested_discount", 0.0)
        qty = params.get("quantity", 1)
        final_unit = params.get("final_unit_price", price)
        orig_unit = params.get("original_price", price)
        total_val = params.get("total_order_value", price * qty)
        reason = params.get("reason", "")
        order_ref = params.get("order_reference", "")
        rzp_order_id = params.get("razorpay_order_id", "")
        status = params.get("status", "")

        # 1. CATALOG WELCOME
        if message_type == "catalog":
            if lang == "hi":
                return (
                    "नमस्ते! हमारे मर्चेंट स्टोर में आपका स्वागत है। हमारे पास प्रीमियम एंटरप्राइज और डेवलपर प्रोडक्ट्स उपलब्ध हैं:\n"
                    f"• **{sku_name}** (`{sku_code}`) - ₹{price:,.2f} (अधिकतम छूट: {max_disc}%)\n\n"
                    "आप किसी भी उत्पाद पर डिस्काउंट के लिए मोलभाव कर सकते हैं या सीधे Razorpay पर सुरक्षित ऑर्डर कर सकते हैं!"
                )
            elif lang == "ta":
                return (
                    "வணக்கம்! எங்கள் வணிக அங்காடிக்கு வரவேற்கிறோம். எங்களிடம் சிறந்த தொழில்நுட்ப தயாரிப்புகள் உள்ளன:\n"
                    f"• **{sku_name}** (`{sku_code}`) - ₹{price:,.2f} (அதிகபட்ச தள்ளுபடி: {max_disc}%)\n\n"
                    "தள்ளுபடி குறித்து பேச அல்லது Razorpay மூலம் உடனடியாக வாங்க எனக்கு செய்தி அனுப்புங்கள்!"
                )
            elif lang == "te":
                return (
                    "నమస్కారం! మా వ్యాపార స్టోర్‌కు స్వాగతం. మా వద్ద అత్యుత్తమ ఉత్పత్తులు అందుబాటులో ఉన్నాయి:\n"
                    f"• **{sku_name}** (`{sku_code}`) - ₹{price:,.2f} (గరిష్ట తగ్గింపు: {max_disc}%)\n\n"
                    "డిస్కౌంట్ కోసం బేరమాడవచ్చు లేదా Razorpay ద్వారా వెంటనే కొనుగోలు చేయవచ్చు!"
                )
            elif lang == "es":
                return (
                    "¡Hola! Bienvenido a nuestra tienda empresarial. Disponemos de productos tecnológicos de alto rendimiento:\n"
                    f"• **{sku_name}** (`{sku_code}`) - ₹{price:,.2f} (Descuento máx.: {max_disc}%)\n\n"
                    "¡Puede negociar un descuento o realizar su pedido directamente con Razorpay!"
                )
            else:
                return (
                    "Welcome to our merchant store! We have high-performance enterprise and developer products:\n"
                    f"• **{sku_name}** (`{sku_code}`) - ₹{price:,.2f} (Max discount: {max_disc}%)\n\n"
                    "Feel free to negotiate a discount or proceed with instant Razorpay checkout!"
                )

        # 2. NEGOTIATION APPROVED
        if message_type == "negotiate_approved":
            if lang == "hi":
                return (
                    f"🚀 **शानदार खबर!** **{sku_name}** (x{qty}) पर **{req_disc:.1f}% छूट** का आपका अनुरोध हमारे Policy Engine द्वारा **स्वीकृत (APPROVED)** कर दिया गया है।\n\n"
                    f"• प्रति यूनिट मूल्य: **₹{final_unit:,.2f}** (पहले ₹{orig_unit:,.2f})\n"
                    f"• कुल ऑर्डर मूल्य: **₹{total_val:,.2f}**\n"
                    f"• पॉलिसी कारण: _{reason}_\n\n"
                    f"क्या आप Razorpay पर भुगतान करके ऑर्डर कन्फर्म करना चाहते हैं?"
                )
            elif lang == "ta":
                return (
                    f"🚀 **சிறந்த செய்தி!** **{sku_name}** (x{qty}) மீதான **{req_disc:.1f}% தள்ளுபடி** கோரிக்கை எங்கள் Policy Engine மூலம் **அங்கீகரிக்கப்பட்டது (APPROVED)**.\n\n"
                    f"• யூனிட் விலை: **₹{final_unit:,.2f}** (முதலில் ₹{orig_unit:,.2f})\n"
                    f"• மொத்த ஆர்டர் மதிப்பு: **₹{total_val:,.2f}**\n"
                    f"• பாலிசி காரணம்: _{reason}_\n\n"
                    f"இப்போது Razorpay மூலம் பாதுகாப்பாக பணம் செலுத்த விரும்புகிறீர்களா?"
                )
            elif lang == "te":
                return (
                    f"🚀 **శుభవార్త!** **{sku_name}** (x{qty}) పై మీ **{req_disc:.1f}% తగ్గింపు** అభ్యర్థన మా Policy Engine ద్వారా **ఆమోదించబడింది (APPROVED)**.\n\n"
                    f"• యూనిట్ ధర: **₹{final_unit:,.2f}** (గతంలో ₹{orig_unit:,.2f})\n"
                    f"• మొత్తం ఆర్డర్ విలువ: **₹{total_val:,.2f}**\n"
                    f"• పాలసీ కారణం: _{reason}_\n\n"
                    f"ఇప్పుడే Razorpay ద్వారా చెల్లింపు చేసి ఆర్డర్ పూర్తి చేయాలనుకుంటున్నారా?"
                )
            elif lang == "es":
                return (
                    f"🚀 **¡Excelente noticia!** Su solicitud de **{req_disc:.1f}% de descuento** en **{sku_name}** (x{qty}) ha sido **APROBADA** por nuestro Policy Engine.\n\n"
                    f"• Precio unitario: **₹{final_unit:,.2f}** (antes ₹{orig_unit:,.2f})\n"
                    f"• Valor total del pedido: **₹{total_val:,.2f}**\n"
                    f"• Razón de política: _{reason}_\n\n"
                    f"¿Desea completar el pago en Razorpay ahora?"
                )
            else:
                return (
                    f"Great news! Your request for **{req_disc:.1f}% discount** on **{sku_name}** (x{qty}) has been **APPROVED** by our Policy Engine.\n\n"
                    f"• Unit Price: **₹{final_unit:,.2f}** (was ₹{orig_unit:,.2f})\n"
                    f"• Total Order Value: **₹{total_val:,.2f}**\n"
                    f"• Policy Reason: _{reason}_\n\n"
                    f"Would you like to complete payment on Razorpay now?"
                )

        # 3. NEGOTIATION REJECTED
        if message_type == "negotiate_rejected":
            if lang == "hi":
                return (
                    f"⚠️ आपके द्वारा मांगी गई **{req_disc:.1f}% छूट** को Policy Engine द्वारा अस्वीकार कर दिया गया है।\n\n"
                    f"• **कारण**: {reason}\n"
                    f"• इस उत्पाद पर अधिकतम अनुमेय छूट: **{max_disc}%** है।\n\n"
                    f"क्या आप अधिकतम **{max_disc}% छूट** के साथ ऑर्डर आगे बढ़ाना चाहते हैं?"
                )
            elif lang == "ta":
                return (
                    f"⚠️ நீங்கள் கோரிய **{req_disc:.1f}% தள்ளுபடி** Policy Engine வரம்பை மீறுவதால் நிராகரிக்கப்பட்டது.\n\n"
                    f"• **காரணம்**: {reason}\n"
                    f"• அதிகபட்ச அனுமதிக்கப்பட்ட தள்ளுபடி: **{max_disc}%**.\n\n"
                    f"சிறந்த அனுமதிக்கப்பட்ட **{max_disc}%** தள்ளுபடியுடன் வாங்க விரும்புகிறீர்களா?"
                )
            elif lang == "te":
                return (
                    f"⚠️ మీరు కోరిన **{req_disc:.1f}% తగ్గింపు** పాలసీ పరిమితిని మించినందున తిరస్కరించబడింది.\n\n"
                    f"• **కారణం**: {reason}\n"
                    f"• గరిష్ట అనుమతించదగిన తగ్గింపు: **{max_disc}%**.\n\n"
                    f"మీ కోసం గరిష్ట **{max_disc}% తగ్గింపుతో** కొనసాగించమంటారా?"
                )
            elif lang == "es":
                return (
                    f"⚠️ Su solicitud de **{req_disc:.1f}% de descuento** no puede ser aprobada.\n\n"
                    f"• **Razón**: {reason}\n"
                    f"• El descuento máximo permitido para este producto es **{max_disc}%**.\n\n"
                    f"¿Desea que apliquemos nuestro descuento máximo permitido de **{max_disc}%** en su lugar?"
                )
            else:
                return (
                    f"I checked with our merchant Policy Engine, but your request for **{req_disc:.1f}% discount** cannot be accepted.\n\n"
                    f"• **Reason**: {reason}\n"
                    f"• The maximum allowable discount on this item is **{max_disc}%**.\n\n"
                    f"Would you like me to apply our best allowable discount of **{max_disc}%** for you instead?"
                )

        # 4. CHECKOUT SUCCESS / PAYMENT READY
        if message_type == "checkout_ready":
            if lang == "hi":
                return (
                    f"🎉 **आपका Razorpay टेस्ट ऑर्डर सफलतापूर्वक जनरेट हो गया है!**\n\n"
                    f"• **ऑर्डर संदर्भ**: `{order_ref}`\n"
                    f"• **Razorpay ऑर्डर आईडी**: `{rzp_order_id}`\n"
                    f"• **कुल राशि**: **₹{total_val:,.2f}**\n"
                    f"• **स्थिति**: `{status}`\n\n"
                    f"Razorpay टेस्ट गेटवे पर सुरक्षित भुगतान करने के लिए तैयार:"
                )
            elif lang == "ta":
                return (
                    f"🎉 **உங்கள் Razorpay சோதனை ஆர்டர் வெற்றிகரமாக உருவாக்கப்பட்டது!**\n\n"
                    f"• **ஆர்டர் குறிப்பு**: `{order_ref}`\n"
                    f"• **Razorpay ஆர்டர் எண்**: `{rzp_order_id}`\n"
                    f"• **மொத்த தொகை**: **₹{total_val:,.2f}**\n"
                    f"• **நிலை**: `{status}`\n\n"
                    f"Razorpay மூலம் பாதுகாப்பாக பணம் செலுத்தலாம்:"
                )
            elif lang == "te":
                return (
                    f"🎉 **మీ Razorpay టెస్ట్ ఆర్డర్ విజయవంతంగా రూపొందించబడింది!**\n\n"
                    f"• **ఆర్డర్ రిఫరెన్స్**: `{order_ref}`\n"
                    f"• **Razorpay ఆర్డర్ ID**: `{rzp_order_id}`\n"
                    f"• **మొత్తం చెల్లింపు**: **₹{total_val:,.2f}**\n"
                    f"• **స్థితి**: `{status}`\n\n"
                    f"Razorpay టెస్ట్ గేట్‌వేలో చెల్లింపు పూర్తి చేయడానికి సిద్ధంగా ఉంది:"
                )
            elif lang == "es":
                return (
                    f"🎉 **¡Su orden de Razorpay en modo prueba se ha generado con éxito!**\n\n"
                    f"• **Referencia de orden**: `{order_ref}`\n"
                    f"• **ID de Razorpay**: `{rzp_order_id}`\n"
                    f"• **Monto total**: **₹{total_val:,.2f}**\n"
                    f"• **Estado**: `{status}`\n\n"
                    f"Listo para pagar de forma segura en Razorpay:"
                )
            else:
                return (
                    f"🎉 Your Razorpay Test Order has been generated successfully!\n\n"
                    f"• **Order Ref**: `{order_ref}`\n"
                    f"• **Razorpay Order ID**: `{rzp_order_id}`\n"
                    f"• **Total Amount**: **₹{total_val:,.2f}**\n"
                    f"• **Status**: `{status}`\n\n"
                    f"Ready for instant Razorpay test payment:"
                )

        # 5. PENDING APPROVAL (HIGH VALUE GATE)
        if message_type == "pending_approval":
            if lang == "hi":
                return (
                    f"⏳ आपका **{sku_name}** (x{qty}) का ऑर्डर कुल **₹{total_val:,.2f}** का है, जो ऑटोमैटिक अप्रूवल सीमा से अधिक है। "
                    f"इसे मर्चेंट प्रबंधन की समीक्षा और अनुमति के लिए `PENDING_APPROVAL` स्थिति में रखा गया है। "
                    f"ऑर्डर संदर्भ: `{order_ref}`।"
                )
            elif lang == "ta":
                return (
                    f"⏳ உங்கள் **{sku_name}** (x{qty}) ஆர்டர் மதிப்பு **₹{total_val:,.2f}**, இது தானியங்கி வரம்பை விட அதிகம். "
                    f"நிர்வாக ஒப்புதலுக்காக `PENDING_APPROVAL` நிலையில் வைக்கப்பட்டுள்ளது. "
                    f"ஆர்டர் குறிப்பு: `{order_ref}`."
                )
            elif lang == "te":
                return (
                    f"⏳ మీ **{sku_name}** (x{qty}) ఆర్డర్ మొత్తం **₹{total_val:,.2f}**, ఇది ఆటోమేటిక్ పరిమితిని మించింది. "
                    f"అనుమతి కోసం `PENDING_APPROVAL` గా ఉంచబడింది. "
                    f"ఆర్డర్ రిఫరెన్స్: `{order_ref}`."
                )
            elif lang == "es":
                return (
                    f"⏳ Su pedido de **{sku_name}** (x{qty}) por un total de **₹{total_val:,.2f}** excede el umbral automático. "
                    f"Ha sido retenido como `PENDING_APPROVAL` para autorización del administrador. "
                    f"Referencia: `{order_ref}`."
                )
            else:
                return (
                    f"Your order for **{sku_name}** (x{qty}) totals **₹{total_val:,.2f}**, which exceeds our automated threshold. "
                    f"It has been routed to merchant management for approval. Order Reference: `{order_ref}`."
                )

        return reason or "Processed successfully."

llm_service = LLMService()
