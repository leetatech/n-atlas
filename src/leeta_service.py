import math
from typing import Any, Dict, List
import httpx
from src.config import (
    LEETA_API_BASE_URL, LEETA_API_KEY, GOOGLE_MAPS_API_KEY,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
)


def validate_coordinates(lat: float, lng: float):
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError("Invalid location coordinates.")


async def geocode_address(address: str) -> Dict[str, Any]:
    if not address.strip():
        raise ValueError("Please provide your full address, including your city.")
    if not GOOGLE_MAPS_API_KEY:
        raise ValueError("Address lookup is not configured. Please contact support.")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": GOOGLE_MAPS_API_KEY},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
    if data.get("status") == "ZERO_RESULTS":
        raise ValueError("Address not found. Please provide a street address and city.")
    if data.get("status") != "OK":
        raise ValueError("Address lookup failed. Please try again later.")
    results = data.get("results", [])
    if len(results) != 1 or results[0].get("partial_match"):
        raise ValueError("Address is ambiguous. Please add your street, city and state.")
    result = results[0]
    if not any(kind in result.get("types", []) for kind in (
        "street_address", "premise", "subpremise", "route", "establishment"
    )):
        raise ValueError("Please provide a street address, not just a city or region.")
    location = result.get("geometry", {}).get("location", {})
    lat, lng = location.get("lat"), location.get("lng")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        raise ValueError("Address lookup returned an invalid location.")
    validate_coordinates(lat, lng)
    return {"address": address.strip(), "lat": lat, "lng": lng}


async def get_nearby_vendors(lat: float, lng: float) -> List[Dict[str, Any]]:
    """
    Fetches gas vendors near the customer's coordinates.
    """
    headers = {
        "x-api-key": LEETA_API_KEY,
        "Content-Type": "application/json"
    }
    
    validate_coordinates(lat, lng)
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{LEETA_API_BASE_URL.rstrip('/')}/vendors/nearby",
            params={"lat": lat, "lng": lng, "radius_km": 10},
            headers=headers,
            timeout=5.0
        )
        response.raise_for_status()
        vendors = response.json()
    if not isinstance(vendors, list):
        raise ValueError("Vendor lookup returned an invalid response.")
    for vendor in vendors:
        if not isinstance(vendor, dict) or not all(
            isinstance(vendor.get(key), str) and vendor[key].strip()
            for key in ("vendor_id", "product_id", "business_name")
        ):
            raise ValueError("Vendor lookup returned incomplete vendor details.")
        distance = vendor.get("distance_km")
        if not isinstance(distance, (int, float)) or not math.isfinite(distance) or distance < 0:
            raise ValueError("Vendor lookup returned an invalid distance.")
    return sorted(vendors, key=lambda vendor: vendor["distance_km"])

async def create_guest_leeta_order(
    customer_phone: str,
    size_kg: float,
    transcription: str,
    product_id: str,
    vendor_id: str,
    address: str,
    lat: float,
    lng: float
) -> Dict[str, Any]:
    """
    Creates a guest gas refill order via the Leeta API using API Key authentication.
    """
    if not all(value.strip() for value in (customer_phone, product_id, vendor_id, address)):
        raise ValueError("An address and selected vendor/product are required to create an order.")
    if not math.isfinite(size_kg) or size_kg <= 0:
        raise ValueError("Gas quantity must be greater than zero.")
    validate_coordinates(lat, lng)
    headers = {
        "x-api-key": LEETA_API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "address": address,
        "customer_id": f"guest_{customer_phone.replace('+', '').strip()}",
        "delivery_method": "onsite_refill",
        "delivery_type": "same_day",
        "gas_weight": float(size_kg),
        "lat": lat,
        "lng": lng,
        "message": f"WhatsApp Voice Order ({size_kg}kg): {transcription}",
        "payment_type": "pay_now",
        "product_id": product_id,
        "vendor_id": vendor_id,
        "schedule": "immediate",
        "services": ["onsite_refill"],
        "total_amount": 0,
        "wallet_amount": 0
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{LEETA_API_BASE_URL.rstrip('/')}/orders/guest",
            json=payload,
            headers=headers,
            timeout=10.0
        )
        response.raise_for_status()
        result = response.json()
    if not isinstance(result, dict) or result.get("status") == "error":
        raise ValueError("Order service returned an invalid or unsuccessful response.")
    return result


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
        response = await client.post(
            url,
            data=data,
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        )
        response.raise_for_status()
