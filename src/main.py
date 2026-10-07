from pathlib import Path
import httpx
import tempfile
import os
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, File, UploadFile
from fastapi.responses import Response, FileResponse    
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from src.config import STORAGE_DIR, TWILIO_AUTH_TOKEN, TWILIO_ACCOUNT_SID
from src.audio_processor import transcode_to_wav_16k
from src.asr_engine import asr_service
from src.intent_parser import extract_gas_order_intent
from src.conversation import handle_user_message

app = FastAPI(title="Leeta WhatsApp Voice & Text Engine")
validator = RequestValidator(TWILIO_AUTH_TOKEN)

@app.get("/static/audio/{filename}")
async def serve_audio_file(filename: str):
    """Serves generated outbound TTS voice notes to Twilio."""
    file_path = STORAGE_DIR / filename
    if file_path.exists():
        return FileResponse(path=file_path, media_type="audio/ogg")
    raise HTTPException(status_code=404, detail="Audio file not found")

async def _download_twilio_audio(media_url: str) -> str:
    """
    Downloads Twilio voice media (.ogg/.amr/.wav) to a temporary local file
    so transformers pipeline can process it.
    """
    auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    async with httpx.AsyncClient() as client:
        response = await client.get(media_url, auth=auth, follow_redirects=True)
        if response.status_code != 200:
            raise ValueError(f"Failed to download audio from Twilio: status {response.status_code}")
        
        # Save audio payload to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp_file:
            tmp_file.write(response.content)
            return tmp_file.name


async def process_incoming_message_background(
    sender_id: str,
    message_sid: str,
    is_voice: bool,
    public_base_url: str,
    media_url: str = None,
    text_content: str = None
):
    """
    Background worker that handles WhatsApp incoming messages.
    Automatically detects Yoruba (yo), Hausa (ha), or Igbo (ig) if it's a voice note.
    """
    raw_text = ""
    detected_lang = "en"
    lang_name = "English"

    if is_voice and media_url:
        temp_audio_path = None
        try:
            print(f"[Worker] Downloading voice note from: {media_url}")
            temp_audio_path = await _download_twilio_audio(media_url)

            # 1. Transcribe & detect spoken language via NCAIR1 ASR models
            asr_result = asr_service.transcribe_and_detect_language(temp_audio_path)
            
            raw_text = asr_result["transcription"]
            detected_lang = asr_result["language"]
            lang_name = asr_result["language_name"]

            print(f"[NCAIR1 ASR Success] Spoken Language: {lang_name} ({detected_lang}) | Transcript: '{raw_text}'")

        except Exception as e:
            print(f"[ASR Background Error]: {e}")
            raw_text = ""
        finally:
            if temp_audio_path and os.path.exists(temp_audio_path):
                os.remove(temp_audio_path)
    else:
        raw_text = text_content or ""
        detected_lang = "en"  # Default for plain text, or pass to text-based language detector

    await handle_user_message(sender_id, message_sid, raw_text, detected_lang)


@app.get("/health")
async def health_check():
    return {"status": "online", "service": "Leeta N-ATLaS Voice Engine"}


@app.post("/test-leeta-voice")
async def test_leeta_voice_endpoint(file: UploadFile = File(...)):
    """Local test endpoint to debug audio files directly"""
    temp_input = STORAGE_DIR / f"test_{file.filename}"
    temp_wav = STORAGE_DIR / f"test_{file.filename}_16k.wav"

    temp_input.write_bytes(await file.read())

    if not transcode_to_wav_16k(temp_input, temp_wav):
        raise HTTPException(status_code=400, detail="FFmpeg transcoding failed.")

    asr_result = asr_service.transcribe_and_detect_language(str(temp_wav))
    transcription = asr_result["transcription"]
    intent = extract_gas_order_intent(transcription)

    if temp_input.exists(): temp_input.unlink()
    if temp_wav.exists(): temp_wav.unlink()

    return {
        "transcription": transcription,
        "parsed_intent": intent,
        "action": "ASK_ADDRESS_AND_VENDOR" if intent["is_gas_order"] else "FIND_NEARBY_VENDORS"
    }


@app.post("/webhook/whatsapp")
async def handle_whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    form_data = await request.form()
    num_media = int(form_data.get("NumMedia", 0))
    sender_id = form_data.get("From", "")
    message_sid = form_data.get("MessageSid", "")
    media_content_type = form_data.get("MediaContentType0", "")
    incoming_body = form_data.get("Body", "").strip()
    if not sender_id or not message_sid:
        raise HTTPException(status_code=400, detail="From and MessageSid are required.")

    public_base_url = str(request.base_url).rstrip("/")
    twiml_response = MessagingResponse()

    is_voice = num_media > 0 and ("audio" in media_content_type or "ogg" in media_content_type or "amr" in media_content_type)

    if is_voice:
        media_url = form_data.get("MediaUrl0", "")
        background_tasks.add_task(
            process_incoming_message_background,
            sender_id=sender_id,
            message_sid=message_sid,
            is_voice=True,
            public_base_url=public_base_url,
            media_url=media_url
        )
        twiml_response.message("Mo ń gbọ́ ohùn yín, ẹ jọ̀wọ́ ẹ dúró fún ìṣẹ́jú kan...")
    else:
        background_tasks.add_task(
            process_incoming_message_background,
            sender_id=sender_id,
            message_sid=message_sid,
            is_voice=False,
            public_base_url=public_base_url,
            text_content=incoming_body
        )
        twiml_response.message("Mo ti gba àkọsílẹ̀ yín...")

    return Response(content=str(twiml_response), media_type="application/xml")
