import time
from pathlib import Path

from faster_whisper import WhisperModel

from app.config import WHISPER_MODEL_SIZE


TEMP_DIR = Path("data/transcribe_temp")
TEMP_TTL_SECONDS = 3600

_model = None


def _ensure_temp_dir():
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_transcription_temp():
    _ensure_temp_dir()
    now = time.time()

    for path in TEMP_DIR.iterdir():
        try:
            if path.is_file() and now - path.stat().st_mtime > TEMP_TTL_SECONDS:
                path.unlink(missing_ok=True)
        except Exception:
            continue


def temp_voice_path(chat_id, file_unique_id=None):
    cleanup_transcription_temp()
    suffix = file_unique_id or int(time.time())
    return TEMP_DIR / f"voice_{chat_id}_{suffix}.ogg"


def _get_model():
    global _model
    if _model is None:
        _model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def transcribe_audio_file(audio_path: str):
    path = Path(audio_path)
    if not path.exists():
        return {"error": "No pude acceder al audio para transcribir."}

    try:
        model = _get_model()
        segments, info = model.transcribe(
            str(path),
            beam_size=5,
            vad_filter=True,
        )
        text = " ".join(segment.text.strip() for segment in segments if segment.text).strip()

        if not text:
            return {"error": "No pude extraer texto de la nota de voz."}

        return {
            "text": text,
            "language": getattr(info, "language", None) or "auto",
        }
    except Exception as exc:
        return {"error": f"No pude transcribir el audio ahora mismo: {exc}"}
