import hashlib
import hashlib
from io import BytesIO
from pathlib import Path
from typing import List, Optional

import requests
from PIL import Image, ImageDraw, ImageFont


CARD_DIR = Path("data/prediction_cards")
LOGO_CACHE_DIR = CARD_DIR / "logos"


def prediction_menu() -> dict:
    return {
        "type": "menu",
        "text": "🔮 PREDICCIONES DEPORTIVAS\n¿Qué quieres predecir?",
        "buttons": [
            [{"text": "⚽ Resultado Partido", "callback_data": "pred:match"}],
            [{"text": "📋 Ver Mis Predicciones", "callback_data": "pred:history"}],
        ],
    }


def team_suggestion_menu(original_query: str, suggestions: list[str], field: str) -> dict:
    team_label = "equipo principal" if field == "team_a" else "rival"
    buttons = [
        [{"text": suggestion, "callback_data": f"pred:suggest:{field}:{index}"}]
        for index, suggestion in enumerate(suggestions[:3])
    ]
    buttons.append([{"text": "✏️ Escribir de nuevo", "callback_data": f"pred:retry:{field}"}])
    return {
        "type": "menu",
        "text": f"🤔 No encontré una coincidencia exacta para '{original_query}'.\n\n¿Quisiste decir este {team_label}?",
        "buttons": buttons,
    }


def _load_font(size: int, bold: bool = False):
    candidates = [
        "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _hex_to_rgb(value: Optional[str], fallback=(255, 255, 255)):
    raw = (value or "").strip().lstrip("#")
    if len(raw) != 6:
        return fallback
    try:
        return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return fallback


def _blend(color_a, color_b, ratio: float):
    ratio = max(0.0, min(1.0, ratio))
    return tuple(int(color_a[i] * (1 - ratio) + color_b[i] * ratio) for i in range(3))


def _luminance(color):
    return (0.299 * color[0]) + (0.587 * color[1]) + (0.114 * color[2])


def _stable_team_color(primary: Optional[str], secondary: Optional[str], fallback):
    primary_rgb = _hex_to_rgb(primary, fallback)
    secondary_rgb = _hex_to_rgb(secondary, fallback)
    if _luminance(primary_rgb) > 190:
        if _luminance(secondary_rgb) < 170:
            return secondary_rgb
        return fallback
    return primary_rgb


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start_size: int, bold: bool = True):
    size = start_size
    while size >= 18:
        font = _load_font(size, bold=bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return font
        size -= 2
    return _load_font(18, bold=bold)


def _download_logo(url: Optional[str], size: int = 180) -> Image.Image:
    fallback = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(fallback)
    draw.ellipse((8, 8, size - 8, size - 8), fill=(255, 255, 255, 18), outline=(255, 255, 255, 180), width=4)
    draw.ellipse((28, 28, size - 28, size - 28), outline=(255, 255, 255, 90), width=2)
    fallback_font = _load_font(40, bold=True)
    text = "FC"
    bbox = draw.textbbox((0, 0), text, font=fallback_font)
    draw.text(
        ((size - (bbox[2] - bbox[0])) // 2, (size - (bbox[3] - bbox[1])) // 2 - 4),
        text,
        fill=(255, 255, 255, 220),
        font=fallback_font,
    )

    if not url:
        return fallback

    try:
        LOGO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.md5(f"{url}|{size}".encode("utf-8")).hexdigest()
        cache_path = LOGO_CACHE_DIR / f"{cache_key}.png"

        if cache_path.exists():
            image = Image.open(cache_path).convert("RGBA")
            if image.size != (size, size):
                image.thumbnail((size, size))
            return image

        response = requests.get(url, timeout=4)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGBA")
        image.thumbnail((size, size))
        canvas = Image.new("RGBA", (size, size), (255, 255, 255, 0))
        x = (size - image.width) // 2
        y = (size - image.height) // 2
        canvas.paste(image, (x, y), image)
        canvas.save(cache_path, format="PNG")
        return canvas
    except Exception:
        return fallback


def _team_short_name(name: str) -> str:
    normalized = (name or "").strip()
    aliases = {
        "real madrid": "Real Madrid",
        "real betis": "Betis",
        "fc barcelona": "Barcelona",
        "barcelona": "Barcelona",
        "atletico madrid": "Atletico",
        "atlético de madrid": "Atletico",
        "real sociedad": "Real Sociedad",
        "rcd espanyol de barcelona": "Espanyol",
        "espanyol": "Espanyol",
        "real valladolid": "Valladolid",
    }
    alias = aliases.get(normalized.lower())
    if alias:
        return alias

    words = normalized.split()
    if len(words) <= 2:
        return normalized or "Equipo"
    return " ".join(words[:2])


def _ordered_prediction_teams(prediction: dict) -> dict:
    venue = (prediction.get("match_info") or {}).get("venue")
    team_a = prediction.get("team_a", "Equipo A")
    team_b = prediction.get("team_b", "Equipo B")

    if venue == "fuera":
        return {
            "home_name": team_b,
            "away_name": team_a,
            "home_logo": prediction.get("team_b_logo"),
            "away_logo": prediction.get("team_a_logo"),
            "home_colors": prediction.get("team_b_colors", {}),
            "away_colors": prediction.get("team_a_colors", {}),
        }

    return {
        "home_name": team_a,
        "away_name": team_b,
        "home_logo": prediction.get("team_a_logo"),
        "away_logo": prediction.get("team_b_logo"),
        "home_colors": prediction.get("team_a_colors", {}),
        "away_colors": prediction.get("team_b_colors", {}),
    }


def build_prediction_card_image(prediction: dict) -> Optional[str]:
    ordered = _ordered_prediction_teams(prediction)
    home_logo = _download_logo(ordered["home_logo"], size=320)
    away_logo = _download_logo(ordered["away_logo"], size=320)
    home_colors = ordered["home_colors"]
    away_colors = ordered["away_colors"]
    left_color = _stable_team_color(home_colors.get("primary"), home_colors.get("secondary"), (38, 82, 160))
    right_color = _stable_team_color(away_colors.get("primary"), away_colors.get("secondary"), (24, 160, 133))

    width, height = 1080, 1080
    image = Image.new("RGBA", (width, height), (7, 11, 20, 255))
    draw = ImageDraw.Draw(image)

    left_dark = _blend(left_color, (6, 10, 18), 0.55)
    right_dark = _blend(right_color, (6, 10, 18), 0.55)
    for x in range(width):
        ratio = x / max(1, width - 1)
        draw.line((x, 0, x, height), fill=_blend(left_dark, right_dark, ratio))

    draw.rectangle((0, 0, width, height), fill=(7, 10, 20, 145))
    draw.rounded_rectangle((26, 26, width - 26, height - 26), radius=44, fill=(9, 14, 26, 222), outline=(255, 255, 255, 34), width=2)

    left_panel = (70, 190, 490, 890)
    right_panel = (590, 190, 1010, 890)
    draw.rounded_rectangle(left_panel, radius=44, fill=(*left_color, 238))
    draw.rounded_rectangle(right_panel, radius=44, fill=(*right_color, 238))
    draw.line((540, 150, 540, 930), fill=(255, 255, 255, 40), width=4)

    left_col_x = left_panel[0] + (left_panel[2] - left_panel[0] - home_logo.width) // 2
    right_col_x = right_panel[0] + (right_panel[2] - right_panel[0] - away_logo.width) // 2
    logo_y = 380
    draw.ellipse((left_col_x - 20, logo_y - 20, left_col_x + home_logo.width + 20, logo_y + home_logo.height + 20), fill=(255, 255, 255, 248))
    draw.ellipse((right_col_x - 20, logo_y - 20, right_col_x + away_logo.width + 20, logo_y + away_logo.height + 20), fill=(255, 255, 255, 248))
    image.alpha_composite(home_logo, (left_col_x, logo_y))
    image.alpha_composite(away_logo, (right_col_x, logo_y))

    CARD_DIR.mkdir(parents=True, exist_ok=True)
    path = CARD_DIR / f"{prediction.get('id', 'prediction')}.png"
    image.convert("RGB").save(path, format="PNG")
    return str(path)


def prediction_result_menu(prediction: dict, chat_id: int) -> dict:
    prob_text = f"{prediction['probability']}%"
    conf_emoji = {"alta": "✅", "media": "⚠️", "baja": "❓"}.get(prediction.get("confidence"), "❓")
    match_info = prediction.get("match_info", {})
    stats_used = prediction.get("stats_used", {})

    text = f"⚽ {prediction.get('team_a', 'Equipo A')} vs {prediction.get('team_b', 'Equipo B')}\n"
    if match_info.get("competition"):
        text += f"🏆 {match_info['competition']}\n"
    if match_info.get("date"):
        text += f"📅 {match_info['date']}\n"
    if match_info.get("venue_name"):
        text += f"📍 {match_info['venue_name']}\n"

    text += (
        f"\n📊 PREDICCIÓN: {prediction['result']}\n"
        f"Probabilidad: {prob_text} {conf_emoji}\n\n"
    )

    if stats_used:
        text += (
            f"📈 Forma reciente: {stats_used.get('recent_points_last5_team_a', 0)} pts vs {stats_used.get('recent_points_last5_team_b', 0)} pts\n"
            f"🛡️ Porterías a cero: {stats_used.get('clean_sheets_team_a', 0)} vs {stats_used.get('clean_sheets_team_b', 0)}\n\n"
        )

    text += "Factores clave:\n" + "\n".join(f"• {f}" for f in prediction.get("factors", []))

    risks = prediction.get("risks", [])
    if risks:
        text += "\n\nRiesgos:\n" + "\n".join(f"• {risk}" for risk in risks)

    buttons = [
        [{"text": "📋 Ver Mis Predicciones", "callback_data": "pred:history"}],
        [{"text": "↻ Nueva Predicción", "callback_data": "pred:new"}],
    ]

    image_path = build_prediction_card_image(prediction)
    if image_path:
        return {
            "type": "prediction_card",
            "image_path": image_path,
            "text": text,
            "buttons": buttons,
        }

    return {"type": "menu", "text": text, "buttons": buttons}


def history_menu(predictions: List[dict], page: int = 0, items_per_page: int = 5) -> dict:
    start = page * items_per_page
    end = start + items_per_page
    page_preds = predictions[start:end]

    if not page_preds:
        return {"type": "text", "text": "📋 No tienes predicciones guardadas."}

    text = f"📋 MIS PREDICCIONES ({len(predictions)} total)\n\n"
    buttons = []

    for pred in page_preds:
        result = pred.get("prediction", {}).get("predicted_result", "X-Y")
        prob = pred.get("probability", 0)
        team_a = pred.get("team_a", "")
        team_b = pred.get("team_b", "")
        competition = pred.get("match_info", {}).get("competition")

        conf_emoji = {"alta": "✅", "media": "⚠️", "baja": "❓"}.get(calculate_confidence(prob), "❓")

        text += (
            f"{conf_emoji} {team_a} vs {team_b}\n"
            f"   Resultado: {result} | Prob: {prob}%\n"
            + (f"   Competición: {competition}\n\n" if competition else "\n")
        )
        buttons.append([
            {
                "text": f"🗑 Eliminar {team_a} vs {team_b}",
                "callback_data": f"pred:delete:{pred.get('id')}:{page}",
            }
        ])

    nav_row = []
    if page > 0:
        nav_row.append({"text": "◀ Anterior", "callback_data": f"pred:history:{page-1}"})

    total_pages = (len(predictions) + items_per_page - 1) // items_per_page
    if page < total_pages - 1:
        nav_row.append({"text": "Siguiente ▶", "callback_data": f"pred:history:{page+1}"})

    if nav_row:
        buttons.append(nav_row)

    buttons.append([{"text": "↻ Volver", "callback_data": "pred:new"}])
    return {"type": "menu", "text": text, "buttons": buttons}


def calculate_confidence(probability: int) -> str:
    if probability >= 75:
        return "alta"
    if probability >= 60:
        return "media"
    return "baja"


def match_prediction_menu(team_a: str, team_b: str = None) -> dict:
    if team_b:
        text = f"⚽ PREDICCIÓN DE PARTIDO\n{team_a} vs {team_b}\n\nAnalizando datos..."
    else:
        text = "⚽ PREDICCIÓN DE PARTIDO\n¿Qué equipo quieres analizar?"

    return {
        "type": "menu",
        "text": text,
        "buttons": [
            [{"text": "📅 Buscar próximo rival", "callback_data": "pred:rival_auto"}],
            [{"text": "✏️ Escribir rival", "callback_data": "pred:rival_manual"}],
        ],
    }


def top_scorer_menu(team_name: str) -> dict:
    return {
        "type": "menu",
        "text": f"🏆 MÁXIMO GOLEADOR\nEquipo: {team_name}\n\n¿Qué temporada quieres analizar?",
        "buttons": [
            [{"text": "📅 2025/26 (Actual)", "callback_data": "pred:season_2025"}],
            [{"text": "📅 2024/25", "callback_data": "pred:season_2024"}],
        ],
    }


def rival_analysis_menu(team_name: str, next_opponent: str) -> dict:
    return {
        "type": "menu",
        "text": f"🎯 PRÓXIMO RIVAL\n{team_name}\nPróximo partido vs: {next_opponent}",
        "buttons": [
            [{"text": "📊 Analizar rival", "callback_data": "pred:analyze_rival"}],
            [{"text": "⚔️ Predicción H2H", "callback_data": "pred:h2h_pred"}],
        ],
    }
