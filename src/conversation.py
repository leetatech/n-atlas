"""Address-first gas vendor discovery and ordering."""

import asyncio
import logging
import re
from weakref import WeakValueDictionary

import httpx

from src.intent_parser import extract_gas_order_intent
from src.leeta_service import (
    create_guest_leeta_order, geocode_address, get_nearby_vendors,
    send_whatsapp_message,
)
from src.session_manager import (
    clear_session, get_session, record_interaction, update_session,
)

logger = logging.getLogger(__name__)
_user_locks = WeakValueDictionary()


class ReplyDeliveryError(RuntimeError):
    pass


async def _reply(phone: str, text: str):
    record_interaction(phone, "outbound", text, get_session(phone)["step"])
    try:
        await send_whatsapp_message(phone, text)
    except httpx.HTTPError as error:
        logger.exception("WhatsApp reply delivery failed")
        record_interaction(phone, "delivery_failed", text, get_session(phone)["step"])
        raise ReplyDeliveryError("WhatsApp reply delivery failed.") from error


async def handle_user_message(
    phone: str, message_sid: str, text: str, language: str = "en"
):
    lock = _user_locks.get(phone)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[phone] = lock
    async with lock:
        session = get_session(phone)
        if not record_interaction(phone, "inbound", text, session["step"], message_sid):
            return
        try:
            await _advance(phone, text.strip(), language)
        except (httpx.HTTPError, ValueError) as error:
            logger.exception("Conversation service failed at step %s", get_session(phone)["step"])
            if isinstance(error, ValueError):
                message = str(error)
            else:
                message = "The location or vendor service is unavailable. Please try again."
            await _reply(phone, message)
        finally:
            record_interaction(phone, "state", "", get_session(phone)["step"])


async def _advance(phone: str, text: str, language: str):
    session = get_session(phone)
    step = session["step"]
    if step in ("creating_order", "order_unknown"):
        await _reply(
            phone, "Your previous order is awaiting verification. Please contact support "
            "before placing another order to avoid a duplicate.",
        )
        return
    if not text:
        await _reply(phone, "I could not understand that message. Please send it again as text.")
        return
    if text.lower() == "cancel":
        clear_session(phone)
        await _reply(phone, "Request cancelled. Send your address to find gas vendors when ready.")
        return
    if step == "order_created":
        clear_session(phone)
        session = get_session(phone)
        step = "idle"

    address_match = re.match(r"^(?:change\s+)?address\s*:\s*(.+)$", text, re.I)
    if text.lower() == "change address" or address_match:
        update_session(phone, {
            "step": "awaiting_address", "address": None, "lat": None, "lng": None,
            "vendors": [], "vendor": None,
        })
        step = "awaiting_address"
        if not address_match:
            await _reply(phone, "Please send your new full street address, including city and state.")
            return
    elif text.lower() == "change vendor" and session.get("address"):
        update_session(phone, {"step": "finding_vendors", "vendor": None})
        await _show_vendors(phone)
        return

    intent = extract_gas_order_intent(text, language) if step != "awaiting_address" else None
    if intent and intent["is_order_declined"]:
        update_session(phone, {"wants_order": False, "order_text": None, "size_kg": None})
        if step == "awaiting_vendor":
            await _reply(phone, "No order will be placed. You can still select a vendor to browse, or reply cancel.")
            return
    if intent and step not in ("awaiting_vendor", "finding_vendors"):
        if intent["is_gas_order"]:
            update_session(phone, {"wants_order": True, "order_text": text})
        if intent["size_kg"] is not None or re.search(r"\b(?:kg|kilos?|kilograms?)\b", text, re.I):
            update_session(phone, {"size_kg": intent["size_kg"]})

    if step == "idle" and not address_match:
        update_session(phone, {"step": "awaiting_address"})
        await _reply(
            phone, "I can help you order gas or find nearby gas vendors. "
            "First, please send your full street address, including city and state.",
        )
        return
    if step == "awaiting_address":
        address = address_match.group(1) if address_match else text
        location = await geocode_address(address)
        update_session(phone, {
            **location, "step": "finding_vendors", "vendors": [], "vendor": None,
        })
        await _show_vendors(phone)
        return
    if step == "finding_vendors":
        await _show_vendors(phone)
        return
    if step == "awaiting_vendor":
        vendors = session["vendors"]
        matches = [
            vendor for vendor in vendors
            if text.casefold() in (vendor["vendor_id"].casefold(), vendor["business_name"].casefold())
        ]
        if text.isdecimal() and 1 <= int(text) <= len(vendors):
            matches = [vendors[int(text) - 1]]
        if len(matches) != 1:
            await _reply(phone, "Please select a vendor using a number from the list, its name or its ID.")
            return
        update_session(phone, {"vendor": matches[0]})
        await _order_or_prompt(phone)
        return
    if step == "awaiting_size":
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            intent = extract_gas_order_intent(f"{text}kg", language)
            update_session(phone, {"size_kg": intent["size_kg"]})
    await _order_or_prompt(phone)


async def _show_vendors(phone: str):
    session = get_session(phone)
    vendors = await get_nearby_vendors(session["lat"], session["lng"])
    update_session(phone, {"vendors": vendors, "vendor": None})
    if not vendors:
        update_session(phone, {"step": "awaiting_address"})
        await _reply(
            phone, "No gas vendors were found within 10 km of that address. "
            "Please send another address, or reply cancel.",
        )
        return
    update_session(phone, {"step": "awaiting_vendor"})
    lines = [
        f"{index}. {vendor['business_name']} ({vendor['distance_km']:g} km)"
        for index, vendor in enumerate(vendors, 1)
    ]
    await _reply(
        phone, "Nearby gas vendors, closest first:\n" + "\n".join(lines)
        + "\nPlease choose a vendor by number, name or ID. "
        "To use a different address, send address: followed by your full address.",
    )


async def _order_or_prompt(phone: str):
    session = get_session(phone)
    if not session.get("address") or not session.get("vendor"):
        raise ValueError("Please provide an address and select a nearby vendor first.")
    if not session.get("wants_order"):
        update_session(phone, {"step": "awaiting_order"})
        await _reply(
            phone, f"You selected {session['vendor']['business_name']}. "
            "To place an order, reply 'order gas' with the quantity in kg, "
            "or reply cancel to finish browsing.",
        )
        return
    if not session.get("size_kg"):
        update_session(phone, {"step": "awaiting_size"})
        await _reply(phone, "How many kg of gas would you like to order? For example, 6kg.")
        return
    update_session(phone, {"step": "creating_order"})
    try:
        result = await create_guest_leeta_order(
            customer_phone=phone,
            size_kg=session["size_kg"],
            transcription=session["order_text"],
            product_id=session["vendor"]["product_id"],
            vendor_id=session["vendor"]["vendor_id"],
            address=session["address"],
            lat=session["lat"],
            lng=session["lng"],
        )
    except (httpx.HTTPError, ValueError):
        # A timeout or malformed response may follow a successful remote write.
        logger.exception("Order outcome could not be verified")
        update_session(phone, {"step": "order_unknown"})
        await _reply(
            phone, "I could not verify whether your order was created. Please contact support "
            "before retrying to avoid a duplicate order.",
        )
        return
    update_session(phone, {"step": "order_created", "order_response": result})
    await _reply(
        phone, f"Your {session['size_kg']:g}kg gas order with "
        f"{session['vendor']['business_name']} was created for {session['address']}.",
    )
