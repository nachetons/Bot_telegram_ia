import requests
from app.config import OPENROUTER_API_KEY, OPENROUTER_URL, OPENROUTER_MODEL


def call_llm_cloud(messages):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",  # 🔥 recomendado por OpenRouter
        "X-Title": "telegram-bot"
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.2
    }

    try:
        r = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=20  # 🔥 más realista
        )

        # -----------------------
        # CHECK HTTP STATUS
        # -----------------------
        if r.status_code != 200:
            print("❌ CLOUD HTTP ERROR:", r.status_code, r.text)
            raise Exception("OpenRouter HTTP error")

        data = r.json()

        # -----------------------
        # CHECK RESPONSE STRUCTURE
        # -----------------------
        if "choices" not in data:
            print("❌ CLOUD INVALID RESPONSE:", data)
            raise Exception("Invalid OpenRouter response")

        return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("❌ CLOUD EXCEPTION:", str(e))
        raise e  # 🔥 IMPORTANTE: subir error para que smart_llm haga fallback