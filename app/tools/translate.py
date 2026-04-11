import re
import time
from pathlib import Path

from deep_translator import GoogleTranslator
from gtts import gTTS


TEMP_DIR = Path("data/translate_temp")
TEMP_TTL_SECONDS = 3600

COMMON_LANGUAGES = [
    ("es", "Español"),
    ("en", "Inglés"),
    ("fr", "Francés"),
    ("de", "Alemán"),
    ("it", "Italiano"),
    ("pt", "Portugués"),
]


LANGUAGE_ALIASES = {
    "es": "es",
    "esp": "es",
    "espanol": "es",
    "español": "es",
    "en": "en",
    "eng": "en",
    "ingles": "en",
    "inglés": "en",
    "fr": "fr",
    "frances": "fr",
    "francés": "fr",
    "de": "de",
    "aleman": "de",
    "alemán": "de",
    "it": "it",
    "italiano": "it",
    "pt": "pt",
    "portugues": "pt",
    "portugués": "pt",
    "ca": "ca",
    "catalan": "ca",
    "catalán": "ca",
    "gl": "gl",
    "gallego": "gl",
    "eu": "eu",
    "euskera": "eu",
    "vasco": "eu",
    "ja": "ja",
    "japones": "ja",
    "japonés": "ja",
    "ko": "ko",
    "coreano": "ko",
    "zh": "zh-CN",
    "chino": "zh-CN",
    "ru": "ru",
    "ruso": "ru",
    "ar": "ar",
    "arabe": "ar",
    "árabe": "ar",
    "auto": "auto",
}


def _ensure_temp_dir():
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_translate_temp():
    _ensure_temp_dir()
    now = time.time()

    for path in TEMP_DIR.iterdir():
        try:
            if path.is_file() and now - path.stat().st_mtime > TEMP_TTL_SECONDS:
                path.unlink(missing_ok=True)
        except Exception:
            continue


def _normalize_language(value: str):
    key = re.sub(r"\s+", " ", (value or "").strip().lower())
    return LANGUAGE_ALIASES.get(key, key)


def _payload_to_text(payload: dict):
    detected_label = "auto" if payload.get("source") == "auto" else payload.get("source")
    return (
        f"Origen: {detected_label}\n"
        f"Destino: {payload.get('target')}\n\n"
        f"{payload.get('translated_text', '')}"
    )


def translate_payload(query: str):
    cleaned = (query or "").strip()
    if not cleaned:
        return {"error": "Indica el texto a traducir."}

    parts = [part.strip() for part in cleaned.split("|")]
    parts = [part for part in parts if part]

    if len(parts) == 2:
        source = "auto"
        target, text = parts
    elif len(parts) >= 3:
        source, target = parts[0], parts[1]
        text = " | ".join(parts[2:]).strip()
    else:
        return {
            "error": (
                "Uso:\n"
                "/translate <destino> | <texto>\n"
                "/translate <origen> | <destino> | <texto>"
            )
        }

    source_lang = _normalize_language(source)
    target_lang = _normalize_language(target)

    if not text:
        return {"error": "Indica el texto que quieres traducir."}

    try:
        translated = GoogleTranslator(source=source_lang, target=target_lang).translate(text)
    except Exception as exc:
        return {"error": f"No pude traducir el texto ahora mismo: {exc}"}

    return {
        "source": source_lang,
        "target": target_lang,
        "original_text": text,
        "translated_text": translated,
        "text": _payload_to_text(
            {
                "source": source_lang,
                "target": target_lang,
                "translated_text": translated,
            }
        ),
    }


def translate_text(query: str):
    payload = translate_payload(query)
    if payload.get("error"):
        return payload["error"]
    return payload["text"]


def translate_language_buttons():
    buttons = []
    for code, label in COMMON_LANGUAGES:
        buttons.append([{"text": label, "callback_data": f"translate_lang:{code}"}])
    return buttons


def build_translate_result_menu(payload: dict):
    return {
        "type": "menu",
        "text": payload["text"],
        "buttons": [[{"text": "🔊 Escuchar pronunciación", "callback_data": f"translate_voice:{payload['target']}"}]],
    }


def generate_translate_audio(text: str, language: str):
    cleanup_translate_temp()
    _ensure_temp_dir()

    clean_text = (text or "").strip()
    clean_language = _normalize_language(language)

    if not clean_text:
        return {"error": "No tengo texto para pronunciar."}

    audio_path = TEMP_DIR / f"tts_{clean_language}_{abs(hash((clean_language, clean_text))) % 10_000_000}.mp3"
    if not audio_path.exists():
        try:
            gTTS(text=clean_text, lang=clean_language).save(str(audio_path))
        except Exception as exc:
            return {"error": f"No pude generar el audio de pronunciación: {exc}"}

    return {
        "type": "local_audio",
        "path": str(audio_path),
        "title": f"Pronunciación ({clean_language})",
        "performer": "Translator",
    }
