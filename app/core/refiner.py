def refine_context(context: str):
    if not context:
        return ""

    # limpia exceso de espacios
    context = " ".join(context.split())

    # corta a tamaño seguro para LLM + Telegram
    return context[:2500]