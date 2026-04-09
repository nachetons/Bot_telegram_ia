def refine_context(context: str):
    if not context:
        return ""

    lines = [line.strip() for line in context.splitlines()]
    compact_lines = []

    for line in lines:
        if not line:
            if compact_lines and compact_lines[-1] != "":
                compact_lines.append("")
            continue

        compact_lines.append(" ".join(line.split()))

    refined = "\n".join(compact_lines).strip()
    return refined[:3000]
