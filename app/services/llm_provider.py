from app.services.llm_client import call_llm
from app.services.llm_client_cloud import call_llm_cloud
from app.config import LM_STUDIO_URL, MODEL_NAME, OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_URL
import logging


def smart_llm(messages):
    local_ready = bool((LM_STUDIO_URL or "").strip() and (MODEL_NAME or "").strip())
    cloud_ready = bool((OPENROUTER_URL or "").strip() and (OPENROUTER_API_KEY or "").strip() and (OPENROUTER_MODEL or "").strip())

    if local_ready:
        try:
            logging.info("🟡 LOCAL LLM")
            return call_llm(messages)
        except Exception as e:
            logging.error("🔴 LOCAL FAIL: %s", e)
    else:
        logging.info("⏭️ LOCAL LLM OMITIDO: config incompleta")

    if cloud_ready:
        try:
            logging.info("🟢 CLOUD LLM")
            return call_llm_cloud(messages)
        except Exception as e:
            logging.error("🔴 CLOUD FAIL: %s", e)
    else:
        logging.info("⏭️ CLOUD LLM OMITIDO: config incompleta")

    logging.error("💀 NO LLM AVAILABLE")
    return "No puedo responder ahora mismo"
