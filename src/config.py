import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path("/tmp/natlas_audio")
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Environment Keys
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
HF_TOKEN = os.getenv("HF_TOKEN", "")

# Leeta Service Settings
LEETA_API_BASE_URL = os.getenv("LEETA_API_BASE_URL", "https://api.getleeta.com/v1")
LEETA_API_KEY = os.getenv("LEETA_API_KEY", "your_leeta_internal_api_key")

# Default ASR Model
ASR_MODEL_NAME = "NCAIR1/Yoruba-ASR"
