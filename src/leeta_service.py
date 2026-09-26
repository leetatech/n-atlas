import os
import httpx
from src.config import LEETA_API_BASE_URL, LEETA_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN

async def create_leeta_draft_order(customer_phone: str, size_kg: float, transcription: str) -> dict:
    """Sends draft order request to Leeta API."""
    payload = {
        "customer_phone": customer_phone,
        "cylinder_size_kg": size_kg,
        "source": "whatsapp_voice_natlas",
        "transcription": transcription
    }

    headers = {
        "Authorization": f"Bearer {LEETA_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{LEETA_API_BASE_URL}/orders/draft",
                json=payload,
                headers=headers,
                timeout=5.0
            )
            if response.status_code in [200, 201]:
                return response.json()
        except Exception as e:
            print(f"[Leeta API Error]: {e}")

    # Local fallback for testing
    return {
        "order_id": f"LTA-{os.urandom(3).hex().upper()}",
        "status": "pending_confirmation",
        "cylinder_size_kg": size_kg,
        "estimated_price_ngn": 12500 if size_kg == 12.5 else int(size_kg * 1000)
    }

async def send_whatsapp_message(to_phone: str, message_body: str, media_url: str = None):
    """
    Sends outbound WhatsApp message via Twilio API.
    Supports optional media_url for sending voice notes.
    """
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN):
        print(f"[Local Preview Reply to {to_phone}]:\nText: {message_body}\nMedia URL: {media_url}")
        return

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    
    data = {
        "From": "whatsapp:+14155238886",
        "To": to_phone,
        "Body": message_body
    }
    if media_url:
        data["MediaUrl"] = media_url

    async with httpx.AsyncClient() as client:
        await client.post(
            url,
            data=data,
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        )
