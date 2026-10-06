# Leeta WhatsApp Voice & Text Engine

A FastAPI application for WhatsApp gas ordering and nearby vendor discovery.
Text and transcribed voice messages use the same tracked conversation flow.

## Configuration

Set environment variables before starting the server (a `.env` file is not
automatically loaded):

- `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` for outbound WhatsApp replies.
  Without them, replies are printed as local previews.
- `LEETA_API_BASE_URL` (default: `https://api.getleeta.com/v1`).
- `LEETA_API_KEY` for vendor lookup and guest orders.
- `GOOGLE_MAPS_API_KEY` with the Google Maps Geocoding API enabled.
- `SESSION_DB_PATH` (default: `data/sessions.sqlite3`) for persistent SQLite
  conversation state and interaction history.
- `HF_TOKEN` if required by the ASR models.

The application uses FastAPI, Uvicorn, HTTPX, Twilio, python-multipart,
ffmpeg-python, PyTorch and Transformers. FFmpeg must also be installed.

## Running

```sh
uvicorn src.main:app --reload
```

Run **one worker**: per-user async locks serialize conversation updates within
the process. Multiple workers or server instances require shared distributed
conversation locking. SQLite retains state and history across restarts.

## Conversation flow

1. Any new request, including a greeting or vendor enquiry, asks for the user's
   full street address, city and state.
2. Google Maps geocodes the address. Missing, ambiguous, partial or city-only
   locations require clarification; no default location is used.
3. The resulting latitude/longitude are sent to Leeta's `/vendors/nearby`
   endpoint with a 10 km radius. Its array response is sorted by `distance_km`.
4. The user must choose a vendor by list number, exact name or vendor ID.
   The selected record supplies both `vendor_id` and `product_id`.
5. Browsing alone never creates an order. A gas-order request and a positive
   quantity in kg are also required. Missing quantity is requested rather than
   silently defaulted. Existing 12kg shorthand is treated as 12.5kg.
6. `/orders/guest` receives the user's address and geocoded coordinates plus
   the chosen vendor/product. Success is reported only after the API responds.

Send `change address`, or `address: <full address>`, to update the location and
clear the previous vendor selection. Send `change vendor` to refresh the list.
Send `cancel` to clear the active conversation; interaction history is retained.
A new conversation after a completed order requires an address and vendor again.

Incoming messages, outgoing reply attempts and resulting conversation steps
are recorded in SQLite. Twilio message IDs prevent a repeated webhook from
creating another order. An interrupted or unverified order is blocked from
automatic retry to prevent duplicate orders; support must reconcile it with
Leeta before clearing that user's session.

The database contains phone numbers, addresses and message text. Restrict access,
back it up appropriately and apply your retention/deletion policy. There is no
public interaction-history endpoint; `src.session_manager.get_interactions`
provides local access for authorized application code.

## Endpoints

- `POST /webhook/whatsapp`: ingest text or voice messages.
- `GET /health`: health check.
- `POST /test-leeta-voice`: transcribe a local audio upload and inspect intent;
  this diagnostic endpoint never creates orders.
- `GET /static/audio/{filename}`: serve generated audio.

Twilio webhook signature enforcement is not yet implemented; restrict public
access until it is configured.

## Tests

```sh
venv/bin/python -m unittest discover -s tests -v
```

Tests mock Google Maps, Leeta and Twilio; no external API requests are made.
