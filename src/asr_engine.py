import torch
from transformers import pipeline
from typing import Dict, Any

MODEL_MAP = {
    "yo": "NCAIR1/Yoruba-ASR",
    "ha": "NCAIR1/Hausa-ASR",
    "ig": "NCAIR1/Igbo-ASR"
}

LANG_NAMES = {
    "yo": "Yoruba",
    "ha": "Hausa",
    "ig": "Igbo"
}

class ASREngine:
    def __init__(self):
        # Dictionary storing lazy-loaded pipelines: {"yo": pipeline, "ha": pipeline, ...}
        self.pipelines: Dict[str, Any] = {}
        # Auto-detect CUDA GPU availability
        self.device = 0 if torch.cuda.is_available() else -1

    def load_model(self, lang_code: str):
        """Lazy-loads a specific language model if not already in memory."""
        if lang_code not in self.pipelines and lang_code in MODEL_MAP:
            model_name = MODEL_MAP[lang_code]
            print(f" Loading NCAIR1 {LANG_NAMES[lang_code]} ASR model ({model_name})...")
            
            self.pipelines[lang_code] = pipeline(
                "automatic-speech-recognition",
                model=model_name,
                device=self.device
            )
            print(f" {LANG_NAMES[lang_code]} ASR model loaded successfully!")

    def transcribe_single(self, wav_path: str, lang_code: str) -> str:
        """Transcribes audio using a specific language model."""
        self.load_model(lang_code)
        pipe = self.pipelines.get(lang_code)
        if not pipe:
            return ""
        
        result = pipe(wav_path)
        return result.get("text", "").strip()

    def transcribe_and_detect_language(self, wav_path: str) -> dict:
        """
        Runs ASR across Yoruba, Hausa, and Igbo models locally.
        Determines the spoken language based on model response length/confidence.
        """
        results = []

        for lang_code in MODEL_MAP.keys():
            try:
                transcript = self.transcribe_single(wav_path, lang_code)
                results.append({
                    "language": lang_code,
                    "language_name": LANG_NAMES[lang_code],
                    "text": transcript,
                    "length": len(transcript)
                })
            except Exception as e:
                print(f"[ASR Error - {lang_code}]: {e}")

        # Pick the model that produced the richest non-empty transcript
        valid_results = [r for r in results if r["text"]]

        if not valid_results:
            return {
                "transcription": "",
                "language": "en",
                "language_name": "English",
                "detected": False
            }

        best_match = max(valid_results, key=lambda x: x["length"])

        return {
            "transcription": best_match["text"],
            "language": best_match["language"],
            "language_name": best_match["language_name"],
            "detected": True
        }

# Singleton instance
asr_service = ASREngine()
