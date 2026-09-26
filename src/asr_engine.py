from transformers import pipeline
from src.config import ASR_MODEL_NAME

# Loads and manages the Hugging Face transformers ASR model pipeline cleanly.
class ASREngine:
    def __init__(self):
        self.pipeline = None

    def load_model(self):
        if self.pipeline is None:
            print(f" Loading N-ATLaS ASR model: {ASR_MODEL_NAME}...")
            self.pipeline = pipeline("automatic-speech-recognition", model=ASR_MODEL_NAME)
            print(" N-ATLaS ASR model loaded successfully!")

    def transcribe(self, wav_path: str) -> str:
        if self.pipeline is None:
            self.load_model()
        result = self.pipeline(wav_path)
        return result.get("text", "")

# Singleton instance
asr_service = ASREngine()
