# whatsapp_automation.py
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
import requests
import sqlite3
import json

app = FastAPI()

# ===== إعدادات OAuth واتساب =====
CLIENT_ID = "791417150389817"        
CLIENT_SECRET = "448b4861c8d6804cffe6ea84bd67a6f0" 
REDIRECT_URI = "https://shopify-whatsapp-integration.vercel.app/oauth-callback"  

# ===== تخزين مؤقت للدومين =====
pending_shops = {}

# ===== إنشاء قاعدة البيانات SQLite =====
conn = sqlite3.connect("whatsapp_saas.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_domain TEXT UNIQUE,
    access_token TEXT,
    phone_number_id TEXT,
    waba_id TEXT
)
""")
conn.commit()

# ============================================================
# 📦 Shopify Webhook
# ============================================================
@app.post("/shopify-webhook")
async def shopify_webhook(request: Request):
    try:
        data = await request.json()
        shop_domain = request.headers.get("x-shopify-shop-domain")
        print("🟢 Shopify Webhook Data:", json.dumps(data, ensure_ascii=False))

        customer = data.get("customer", {}) or {}
        customer_name = customer.get("first_name", "Customer")
        phone = customer.get("phone")
        order_id = data.get("id", "N/A")
        total = data.get("total_price", "0")

        if not phone:
            print("⚠️ No phone number found in order")
            return {"status": "no phone in order"}

        # ✅ تحويل الرقم لصيغة دولية
        phone = phone.strip().replace(" ", "")
        if phone.startswith("0"):
            phone = "+20" + phone[1:]
        elif not phone.startswith("+20"):
            phone = "+20" + phone

        # 🔹 جلب التوكن من قاعدة البيانات
        cursor.execute("SELECT access_token, phone_number_id FROM stores WHERE shop_domain=?", (shop_domain,))
        row = cursor.fetchone()
        if not row:
            return {"error": "store not connected to WhatsApp"}
        access_token, phone_number_id = row

        print(f"📞 Sending message to {phone} using phone_number_id {phone_number_id}")

        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": {
                "name": "order_confirmation",
                "language": {"code": "en"},
                "components": [
                    {"type": "body",
                     "parameters": [
                         {"type": "text", "text": customer_name},
                         {"type": "text", "text": str(order_id)},
                         {"type": "text", "text": str(total)},
                     ]},
                ],
            },
        }

        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        resp = requests.post(
            f"https://graph.facebook.com/v22.0/{phone_number_id}/messages",
            headers=headers, json=payload
        )
        print("✅ WhatsApp API Response:", resp.text)

        return {"status": "message_sent", "whatsapp_resp": resp.text}

    except Exception as e:
        print("❌ Shopify webhook error:", e)
        return {"error": str(e)}

# ============================================================
# 💬 WhatsApp Webhook
# ============================================================
@app.post("/whatsapp-webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    print("📩 Incoming WhatsApp Webhook:", json.dumps(data, ensure_ascii=False))
    try:
        entry = data.get("entry", [])
        if not entry:
            return {"status": "no entry"}

        changes = entry[0].get("changes", [])
        if not changes:
            return {"status": "no changes"}

        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return {"status": "no messages"}

        message = messages[0]
        phone = message.get("from")
        text = message.get("text", {}).get("body", "").strip()

        print(f"💬 Message from {phone}: {text}")

        if text == "1":
            reply = "✅ Your order has been confirmed. Thank you!"
        elif text == "2":
            reply = "❌ Your order has been canceled."
        else:
            reply = "Please reply with 1 to confirm or 2 to cancel."

        payload = {"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": reply}}

        cursor.execute("SELECT access_token FROM stores LIMIT 1")
        access_token = cursor.fetchone()[0]

        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        resp = requests.post("https://graph.facebook.com/v22.0/me/messages", headers=headers, json=payload)
        print("📤 Reply sent:", resp.text)

    except Exception as e:
        print("❌ whatsapp webhook error:", e)

    return {"status": "ok"}

# ============================================================
# 🧩 OAuth - ربط المتجر بواتساب
# ============================================================
@app.get("/connect-whatsapp")
def connect_whatsapp(shop_domain: str):
    # حفظ الدومين مؤقتًا
    pending_shops["current"] = shop_domain
    oauth_url = (
        f"https://www.facebook.com/v16.0/dialog/oauth?"
        f"client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope=whatsapp_business_messaging"
    )
    return RedirectResponse(oauth_url)

@app.get("/oauth-callback")
def oauth_callback(code: str):
    shop_domain = pending_shops.get("current", "unknown-shop")
    print(f"🔁 OAuth callback for shop: {shop_domain}")

    token_resp = requests.get(
        f"https://graph.facebook.com/v16.0/oauth/access_token"
        f"?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&client_secret={CLIENT_SECRET}&code={code}"
    )
    data = token_resp.json()
    access_token = data["access_token"]

    me = requests.get(f"https://graph.facebook.com/v16.0/me?fields=whatsapp_business_accounts&access_token={access_token}").json()
    waba_id = me["whatsapp_business_accounts"]["data"][0]["id"]
    phone_number_id = requests.get(f"https://graph.facebook.com/v16.0/{waba_id}/phone_numbers?access_token={access_token}").json()["data"][0]["id"]

    cursor.execute("""
        INSERT OR REPLACE INTO stores (shop_domain, access_token, phone_number_id, waba_id)
        VALUES (?, ?, ?, ?)
    """, (shop_domain, access_token, phone_number_id, waba_id))
    conn.commit()
    return {"status": "connected", "shop": shop_domain}

# ============================================================
# 🧩 للتحقق من Webhook (Meta Verification)
# ============================================================
@app.get("/whatsapp-webhook")
async def verify_whatsapp(request: Request):
    params = dict(request.query_params)
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == "my_verify_token":
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return {"error": "verification failed"}

# ============================================================
# Entry point for Vercel
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
