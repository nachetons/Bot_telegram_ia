from app.core.chat_state import set_translate_session
from app.services.telegram_client import download_telegram_file


def handle_translate_voice_input(chat_id, file_id, file_unique_id=None):
    from app.tools.translate import translate_language_buttons
    from app.tools.transcription import temp_voice_path, transcribe_audio_file

    local_path = download_telegram_file(file_id, str(temp_voice_path(chat_id, file_unique_id)))
    if not local_path:
        return "No pude descargar la nota de voz."

    transcript = transcribe_audio_file(local_path)
    if transcript.get("error"):
        return transcript["error"]

    detected_text = transcript.get("text", "").strip()
    if not detected_text:
        return "No pude entender la nota de voz."

    set_translate_session(chat_id, "await_language", detected_text)
    return {
        "type": "menu",
        "text": (
            f"Texto detectado:\n{detected_text}\n\n"
            "¿A qué idioma quieres traducirlo?"
        ),
        "buttons": translate_language_buttons(),
    }
