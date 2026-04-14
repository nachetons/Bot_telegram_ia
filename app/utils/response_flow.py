from app.services.telegram_client import (
    delete_message,
    edit_message,
    send_chat_action,
    send_message,
)


def typing_indicator(chat_id, stop_event):
    while not stop_event.is_set():
        send_chat_action(chat_id, "typing")
        stop_event.wait(4)


def placeholder_indicator(chat_id, message_id, stop_event):
    frames = [
        "Buscando",
        "Buscando.",
        "Buscando..",
        "Buscando...",
    ]
    index = 0

    while not stop_event.is_set() and message_id:
        edit_message(chat_id, message_id, frames[index])
        index = (index + 1) % len(frames)
        stop_event.wait(1)


def finalize_text_response(chat_id, result, placeholder_message_id=None, stop_placeholder=None):
    message_text = str(result)

    if stop_placeholder:
        stop_placeholder.set()

    if placeholder_message_id:
        edit_message(chat_id, placeholder_message_id, message_text)
    else:
        send_message(chat_id, message_text)


def clear_placeholder(chat_id, placeholder_message_id=None, stop_placeholder=None):
    if stop_placeholder:
        stop_placeholder.set()

    if placeholder_message_id:
        delete_message(chat_id, placeholder_message_id)
