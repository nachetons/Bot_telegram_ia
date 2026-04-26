import requests
from app.config import LM_STUDIO_URL, MODEL_NAME


def call_llm(messages):
    payload = {
        "model": MODEL_NAME,
        "temperature": 0.2,
        "stream": False,
        "messages": messages
    }

    try:
        r = requests.post(
            LM_STUDIO_URL,
            json=payload,
            timeout=(1, 2)
        )

        # -----------------------
        # CHECK HTTP STATUS
        # -----------------------
        if r.status_code != 200:
            print("❌ LOCAL LLM HTTP ERROR:", r.status_code, r.text)
            raise Exception("LM Studio HTTP error")

        data = r.json()

        # -----------------------
        # CHECK STRUCTURE
        # -----------------------
        if "choices" not in data:
            print("❌ LOCAL LLM INVALID RESPONSE:", data)
            raise Exception("Invalid LM response")

        return data["choices"][0]["message"]["content"]

    except requests.exceptions.Timeout:
        print("⏱️ LOCAL LLM TIMEOUT")
        raise Exception("Local LLM timeout")

    except requests.exceptions.ConnectionError:
        print("🔌 LOCAL LLM CONNECTION ERROR")
        raise Exception("Local LLM not available")

    except Exception as e:
        print("❌ LOCAL LLM ERROR:", str(e))
        raise
