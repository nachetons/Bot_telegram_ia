from app.services.llm_client import call_llm
from app.services.llm_client_cloud import call_llm_cloud
import logging


def smart_llm(messages):
    try:
        logging.info("🟡 LOCAL LLM")
        return call_llm(messages)
    except Exception as e:
        logging.error("🔴 LOCAL FAIL: %s", e)

    try:
        logging.info("🟢 CLOUD LLM")
        return call_llm_cloud(messages)
    except Exception as e:
        logging.error("🔴 CLOUD FAIL: %s", e)

    logging.error("💀 NO LLM AVAILABLE")
    return "No puedo responder ahora mismo"