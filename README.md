# WhatsApp Ingestion App

This is a FastAPI application designed to handle incoming WhatsApp messages and convert audio files to WAV format.

## Installation

1. Clone this repository.
2. Install dependencies:
   ```sh
   pip install fastapi uvicorn ffmpeg-python
   ```

## Running the App

1. Start the FastAPI server:
   ```sh
   uvicorn src.main:app --reload
   ```

2. Access the test endpoint:
   ```
   http://127.0.0.1:8000/test
   ```

## Endpoints

- **POST /webhook/whatsapp**: Endpoint to handle incoming WhatsApp webhooks.
- **GET /test**: Test endpoint to verify the server is running.

## Notes

- Ensure `ffmpeg` is installed and accessible in your environment.
- Twilio X-Twilio-Signature validation logic needs to be implemented in the `verify_twilio_signature` function.
- Audio download and conversion logic needs to be implemented in the `download_and_convert_audio` function.
```