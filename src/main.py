from pathlib import Path
import httpx
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, File, UploadFile
from fastapi.responses import Response, FileResponse    
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from src.config import STORAGE_DIR, TWILIO_AUTH_TOKEN, TWILIO_ACCOUNT_SID
from src.audio_processor import transcode_to_wav_16k
from src.asr_engine import asr_service
from src.intent_parser import extract_gas_order_intent
from src.leeta_service import create_leeta_draft_order, send_whatsapp_message

app = FastAPI(title="Leeta WhatsApp Voice & Text Engine")
validator = RequestValidator(TWILIO_AUTH_TOKEN)

@app.get("/static/audio/{filename}")
async def serve_audio_file(filename: str):
    """Serves generated outbound TTS voice notes to Twilio."""
    file_path = STORAGE_DIR / filename
    if file_path.exists():
        return FileResponse(path=file_path, media_type="audio/ogg")
    raise HTTPException(status_code=404, detail="Audio file not found")


async def process_incoming_message_background(
    sender_id: str, 
    message_sid: str, 
    is_voice: bool, 
    text_content: str = None, 
    media_url: str = None,
    public_base_url: str = ""
):
    """Processes message (text or voice note) and matches input format on reply."""
    raw_text = ""

    # 1. Obtain input text (direct or transcribed)
    if is_voice and media_url:
        raw_file = STORAGE_DIR / f"{message_sid}.ogg"
        wav_file = STORAGE_DIR / f"{message_sid}_16k.wav"

        async with httpx.AsyncClient() as client:
            res = await client.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), follow_redirects=True)
            if res.status_code == 200:
                raw_file.write_bytes(res.content)
            else:
                return

        if not transcode_to_wav_16k(raw_file, wav_file):
            return

        raw_text = asr_service.transcribe(str(wav_file))
        
        if raw_file.exists(): raw_file.unlink()
        if wav_file.exists(): wav_file.unlink()
    else:
        raw_text = text_content or ""

    # 2. Extract Intent & Cylinder Size
    intent = extract_gas_order_intent(raw_text)

    # 3. Formulate Text Response
    if intent["is_order_intent"] and intent["cylinder_size_kg"]:
        size = intent["cylinder_size_kg"]
        order = await create_leeta_draft_order(sender_id, size, raw_text)

        reply_text = (
            f"Ẹ ṣeun! A ti gba ìbéèrè yín tí gáàsì {size}kg nínú Leeta. "
            f"Ọ̀pọ̀lọpọ̀ Owo ni ₦{order.get('estimated_price_ngn', 'N/A'):,}. "
            f"Order ID ni {order.get('order_id')}. "
            f"Ṣẹ́ e fẹ́ kí á fi ránṣẹ́ sí ilé yín? Ṣe àtìlẹ́yìn pẹ̀lú 'BẸ́Ẹ̀ NI' láti tẹ̀síwájú."
        )
    elif intent["is_order_intent"]:
        reply_text = (
            f"A gbọ́ pé ẹ fẹ́ ra gáàsì! "
            f"Ẹ jọ̀wọ́, kg kílógírámù mélòó ni ẹ fẹ́ ra? Àpẹẹrẹ: 6kg, 12.5kg, 25kg."
        )
    else:
        reply_text = (
            f"A gbọ́ àkọsílẹ̀ yín: '{raw_text}'. "
            f"Ẹ le sọ fún wa bí ẹ ṣe fẹ́ ra gáàsì Leeta."
        )

    # 4. Deliver response matching incoming modality (Voice -> Voice, Text -> Text)
    if is_voice:
        output_ogg_filename = f"reply_{message_sid}.ogg"
        output_ogg_path = STORAGE_DIR / output_ogg_filename
        
        # Generate TTS audio file
        if generate_tts_ogg(reply_text, output_ogg_path):
            audio_public_url = f"{public_base_url}/static/audio/{output_ogg_filename}"
            await send_whatsapp_message(sender_id, message_body=" Voice note reply from Leeta:", media_url=audio_public_url)
        else:
            # Fallback to text if TTS fails
            await send_whatsapp_message(sender_id, message_body=reply_text)
    else:
        await send_whatsapp_message(sender_id, message_body=reply_text)


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

    transcription = asr_service.transcribe(str(temp_wav))
    intent = extract_gas_order_intent(transcription)

    if temp_input.exists(): temp_input.unlink()
    if temp_wav.exists(): temp_wav.unlink()

    return {
        "transcription": transcription,
        "parsed_intent": intent,
        "action": "TRIGGER_LEETA_ORDER" if intent["is_order_intent"] and intent["cylinder_size_kg"] else "ASK_CLARIFICATION"
    }


@app.post("/webhook/whatsapp")
async def handle_whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    form_data = await request.form()
    num_media = int(form_data.get("NumMedia", 0))
    sender_id = form_data.get("From", "")
    message_sid = form_data.get("MessageSid", "")
    media_content_type = form_data.get("MediaContentType0", "")

    twiml_response = MessagingResponse()

    if num_media > 0 and ("audio" in media_content_type or "ogg" in media_content_type):
        media_url = form_data.get("MediaUrl0", "")
        background_tasks.add_task(
            process_incoming_message_background,
            media_url=media_url,
            sender_id=sender_id,
            message_sid=message_sid
        )
        twiml_response.message(" Mo ń gbọ́ ohùn yín, ẹ jọ̀wọ́ ẹ dúró fún ìṣẹ́jú kan...")
    else:
        twiml_response.message("Ẹ kaabọ́ sí Leeta! Ẹ le fi ohùn ránṣẹ́ láti ra gáàsì (àpẹẹrẹ: 'Mo fẹ́ ra gáàsì 12.5kg').")

    return Response(content=str(twiml_response), media_type="application/xml")
