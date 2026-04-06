from app.services.llm_client import call_llm
from app.services.llm_client_cloud import call_llm_cloud


def smart_llm(messages):
    try:
        print("🟡 LOCAL LLM")
        return call_llm(messages)
    except Exception as e:
        print("🔴 LOCAL FAIL:", e)

    try:
        print("🟢 CLOUD LLM")
        return call_llm_cloud(messages)
    except Exception as e:
        print("🔴 CLOUD FAIL:", e)

    print("💀 NO LLM AVAILABLE")
    return "No puedo responder ahora mismo"