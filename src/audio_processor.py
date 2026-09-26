import subprocess
from pathlib import Path
from gtts import gTTS

def transcode_to_wav_16k(input_path: Path, output_path: Path) -> bool:
    """Converts input audio to 16kHz 16-bit PCM mono WAV for N-ATLaS ASR using FFmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(output_path)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[FFmpeg Error]: {e.stderr.decode()}")
        return False

def generate_tts_ogg(text: str, output_ogg_path: Path, lang: str = "yo") -> bool:
    """
    Generates a speech audio file from text and converts it to 
    WhatsApp-compatible OGG Opus format.
    """
    temp_mp3 = output_ogg_path.parent / f"temp_{output_ogg_path.stem}.mp3"
    try:
        # Generate raw speech MP3
        tts = gTTS(text=text, lang=lang)
        tts.save(str(temp_mp3))

        # Transcode MP3 to WhatsApp-native OGG/Opus
        cmd = [
            "ffmpeg", "-y",
            "-i", str(temp_mp3),
            "-c:a", "libopus",
            "-b:a", "24k",
            str(output_ogg_path)
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        if temp_mp3.exists():
            temp_mp3.unlink()
        return True
    except Exception as e:
        print(f"[TTS Generation Error]: {e}")
        if temp_mp3.exists():
            temp_mp3.unlink()
        return False
        