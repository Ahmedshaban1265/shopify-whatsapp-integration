# whatsapp_automation.py
from fastapi import FastAPI, Request, Response
import requests
import os
import json
from datetime import datetime

app = FastAPI()

# ===== إعدادات واتساب =====
WHATSAPP_API_URL = "https://graph.facebook.com/v22.0/846928455172673/messages"
ACCESS_TOKEN = os.getenv(
    "ACCESS_TOKEN",
    "EAALPyioePjkBP2ZCPkZBJOlUbBdzuM3DIjX6MZC0KNfgDMZCNLSud6ZAxOWBL4JVDmAZBeTtJZAe3ZBwlKwUQjZA5f8kVDIHhL67XkYXSR4TAwvpONzeMUUZAgYmaabNKZC9ol6KBlIpriXbZBiAdvZAyHfIRnce1S5KcocqphMljNfG1uLWhLPWBvES0hMM5YDV4VgrZAb45ZAttPs2Oab2MA7PiNPJNXqElaAxgWorCZCzTE3GWiJ6gbGMmMLygEA1YldM51MZD"
)

# ===== أداة تسجيل بسيطة =====
def log_event(filename, data):
    """يسجل البيانات في ملف JSON مع الوقت"""
    with open(filename, "a", encoding="utf-8") as f:
        log_entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data": data
        }
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

# ============================================================
# 📦 Webhook من Shopify: يرسل رسالة واتساب عند إنشاء أوردر جديد
# ============================================================
@app.post("/shopify-webhook")
async def shopify_webhook(request: Request):
    data = await request.json()

    # سجل البيانات الواردة من Shopify
    log_event("shopify_logs.txt", data)

    customer = data.get("customer", {}) or {}
    customer_name = customer.get("first_name", "Customer")
    phone = customer.get("phone")
    order_id = data.get("id", "N/A")
    total = data.get("total_price", "0")

    # لو مفيش رقم هاتف في الطلب
    if not phone:
        print("⚠️ No phone number found in order")
        return {"status": "no phone in order"}

    # ✅ تحويل الرقم لصيغة دولية (افتراضي مصر)
    phone = phone.strip().replace(" ", "")
    if phone.startswith("0"):
        phone = "+20" + phone[1:]
    elif not phone.startswith("+20"):
        phone = "+20" + phone

    print(f"📞 Sending message to {phone}")

    # قالب واتساب
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": "order_confirmation",  # اسم القالب في Meta
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": customer_name},
                        {"type": "text", "text": str(order_id)},
                        {"type": "text", "text": str(total)},
                    ],
                }
            ],
        },
    }

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    resp = requests.post(WHATSAPP_API_URL, headers=headers, json=payload)
    print("✅ Sent order confirmation message:", resp.text)

    # سجل الرد مع رقم الهاتف والطلب
    log_event("whatsapp_sent.txt", {
        "order_id": order_id,
        "phone": phone,
        "response": resp.text
    })

    return {"status": "message_sent", "whatsapp_resp": resp.text}


# ============================================================
# 💬 Webhook من WhatsApp: يرد على العميل حسب الرسالة
# ============================================================
@app.post("/whatsapp-webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    log_event("whatsapp_incoming.txt", data)

    try:
        entry = data.get("entry", [])
        if not entry:
            print("⚠️ No entry in webhook data")
            return {"status": "no entry"}

        changes = entry[0].get("changes", [])
        if not changes:
            print("⚠️ No changes in webhook data")
            return {"status": "no changes"}

        value = changes[0].get("value", {})
        messages = value.get("messages", [])

        if not messages:
            print("⚠️ No messages found (might be a status update)")
            return {"status": "no messages"}

        message = messages[0]
        phone = message.get("from")
        text = message.get("text", {}).get("body", "").strip()

        print(f"📩 Received message from {phone}: {text}")

        # الرد على العميل
        if text == "1":
            reply = "✅ Your order has been confirmed. Thank you for shopping with us!"
        elif text == "2":
            reply = "❌ Your order has been canceled as requested."
        else:
            reply = "Please reply with 1 to confirm or 2 to cancel your order."

        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": reply},
        }

        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }

        resp = requests.post(WHATSAPP_API_URL, headers=headers, json=payload)
        print("📤 Reply sent:", resp.text)
        log_event("whatsapp_sent.txt", resp.text)

    except Exception as e:
        print("❌ whatsapp webhook error:", e)
        log_event("errors.txt", str(e))

    return {"status": "ok"}


# ============================================================
# 🧩 للتحقق من Webhook (Meta Verification)
# ============================================================
@app.get("/whatsapp-webhook")
async def verify_whatsapp(request: Request):
    params = dict(request.query_params)
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == "my_verify_token"
    ):
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return {"error": "verification failed"}

# ==========================
# Entry point for Vercel
# ==========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
