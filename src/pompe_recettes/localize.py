from __future__ import annotations

import math
import re
from functools import lru_cache

from deep_translator import GoogleTranslator

from pompe_recettes.models import Recipe


FRACTION_MAP = {
    "¼": 0.25,
    "½": 0.5,
    "¾": 0.75,
    "⅐": 1 / 7,
    "⅑": 1 / 9,
    "⅒": 0.1,
    "⅓": 1 / 3,
    "⅔": 2 / 3,
    "⅕": 0.2,
    "⅖": 0.4,
    "⅗": 0.6,
    "⅘": 0.8,
    "⅙": 1 / 6,
    "⅚": 5 / 6,
    "⅛": 0.125,
    "⅜": 0.375,
    "⅝": 0.625,
    "⅞": 0.875,
}

UNIT_CONVERSIONS = {
    "teaspoon": ("ml", 5),
    "teaspoons": ("ml", 5),
    "tsp": ("ml", 5),
    "tablespoon": ("ml", 15),
    "tablespoons": ("ml", 15),
    "tbsp": ("ml", 15),
    "cup": ("ml", 240),
    "cups": ("ml", 240),
    "fluid ounce": ("ml", 30),
    "fluid ounces": ("ml", 30),
    "fl oz": ("ml", 30),
    "ounce": ("g", 28.3495),
    "ounces": ("g", 28.3495),
    "oz": ("g", 28.3495),
    "pound": ("g", 453.592),
    "pounds": ("g", 453.592),
    "lb": ("g", 453.592),
    "lbs": ("g", 453.592),
    "inch": ("cm", 2.54),
    "inches": ("cm", 2.54),
    "in": ("cm", 2.54),
}

FRACTION_CHARS = "¼½¾⅓⅔⅛⅜⅝⅞"
QUANTITY_TOKEN = rf"(?:\d+(?:[.,]\d+)?(?:\s+[{FRACTION_CHARS}])?|\d+[{FRACTION_CHARS}]|\d+/\d+|[{FRACTION_CHARS}])"
UNIT_PATTERN = re.compile(
    rf"(?P<quantity>{QUANTITY_TOKEN}(?:\s*-\s*{QUANTITY_TOKEN})?)"
    r"\s*"
    r"(?P<unit>fluid ounces?|fl oz|tablespoons?|tbsp|teaspoons?|tsp|cups?|ounces?|oz|pounds?|lbs?|inch(?:es)?|in)\b",
    re.IGNORECASE,
)

FAHRENHEIT_PATTERN = re.compile(r"(?P<temp>\d{2,3})\s*°?\s*F\b", re.IGNORECASE)
SERVINGS_PATTERN = re.compile(r"\bservings?\b", re.IGNORECASE)
TEMPERATURE_PATTERN = re.compile(r"(?P<temp>\d{2,3})\s*°(?!C\b)", re.IGNORECASE)

FRENCH_GLOSSARY = {
    "black pepper": "poivre noir",
    "olive oil": "huile d'olive",
    "salt and pepper": "sel et poivre",
    "tomato puree": "purée de tomates",
    "fresh mozzarella": "mozzarella fraîche",
    "parmesan cheese": "parmesan",
    "grated parmesan": "parmesan râpé",
    "parmesan": "parmesan",
    "broccoli florets": "fleurons de brocoli",
    "broccoli": "brocoli",
    "garlic": "ail",
    "minced": "haché",
    "chopped": "haché",
    "divided": "à répartir",
    "cooked": "cuit",
    "short pasta": "pâtes courtes",
    "ground beef": "bœuf haché",
    "lean": "maigre",
    "white sauce": "sauce blanche",
    "fresh basil": "basilic frais",
    "basil leaves": "feuilles de basilic",
    "water": "eau",
    "clove": "gousse",
    "dash": "trait",
    "dashes": "traits",
    "preheat": "préchauffer",
    "bake": "cuire au four",
    "stir": "mélanger",
    "mix": "mélanger",
    "drain": "égoutter",
    "cook": "cuire",
    "serve": "servir",
    "enjoy": "bon appétit",
}

FRENCH_SOURCE_SITES = {
    "colruyt.be",
    "equifrais.be",
    "sofiedumont.fr",
    "visitwallonia.be",
}


def localize_recipe(
    recipe: Recipe, translate_to_french: bool, force_translation: bool = False
) -> Recipe:
    should_translate = translate_to_french and (
        force_translation or recipe.site_name not in FRENCH_SOURCE_SITES
    )

    ingredient_texts = localize_texts(
        recipe.ingredients,
        translate=should_translate,
        text_kind="ingredient",
    )
    instruction_texts = localize_texts(
        recipe.instructions,
        translate=should_translate,
        text_kind="instruction",
    )
    title_text = localize_text(recipe.title, translate=should_translate, text_kind="title")
    description_text = localize_text(
        recipe.description, translate=should_translate, text_kind="description"
    )

    localized = Recipe(
        title=recipe.title,
        source_url=recipe.source_url,
        author=recipe.author,
        description=recipe.description,
        yields=localize_text(recipe.yields, translate=False, text_kind="generic"),
        total_time=recipe.total_time,
        prep_time=recipe.prep_time,
        cook_time=recipe.cook_time,
        image=recipe.image,
        ingredients=ingredient_texts,
        instructions=instruction_texts,
        site_name=recipe.site_name,
    )

    localized.title = title_text or recipe.title
    localized.description = description_text
    return localized


def localize_text(text: str | None, translate: bool, text_kind: str) -> str | None:
    if not text:
        return text
    normalized = normalize_units(text)
    normalized = SERVINGS_PATTERN.sub("portions", normalized)
    if not translate:
        return postprocess_french_text(normalized, text_kind=text_kind)
    translated = translate_text(normalized)
    return postprocess_french_text(translated, text_kind=text_kind)


def localize_texts(texts: list[str], translate: bool, text_kind: str) -> list[str]:
    normalized_texts = [
        SERVINGS_PATTERN.sub("portions", normalize_units(text))
        for text in texts
        if text
    ]
    if not translate:
        return [postprocess_french_text(text, text_kind=text_kind) for text in normalized_texts]

    translated_texts = translate_texts(normalized_texts)
    return [postprocess_french_text(text, text_kind=text_kind) for text in translated_texts]


@lru_cache(maxsize=256)
def translate_text(text: str) -> str:
    try:
        return _get_translator().translate(text)
    except Exception:
        return text


def translate_texts(texts: list[str]) -> list[str]:
    if not texts:
        return []

    unique_texts = list(dict.fromkeys(texts))
    try:
        translated_batch = _get_translator().translate_batch(unique_texts)
    except Exception:
        translated_batch = [translate_text(text) for text in unique_texts]

    translated_map = {
        source: (translated or source)
        for source, translated in zip(unique_texts, translated_batch, strict=False)
    }
    return [translated_map.get(text, text) for text in texts]


@lru_cache(maxsize=1)
def _get_translator() -> GoogleTranslator:
    return GoogleTranslator(source="auto", target="fr")


def normalize_units(text: str) -> str:
    converted = UNIT_PATTERN.sub(_replace_unit_match, text)
    converted = FAHRENHEIT_PATTERN.sub(_replace_fahrenheit_match, converted)
    converted = TEMPERATURE_PATTERN.sub(_replace_bare_temperature_match, converted)
    return converted


def postprocess_french_text(text: str, text_kind: str) -> str:
    normalized = _apply_french_glossary(text)
    normalized = normalized.replace("Ingredients", "Ingrédients")
    normalized = normalized.replace("Preparation", "Préparation")
    normalized = normalized.replace("traits de poivre noir", "traits de poivre noir")

    if text_kind == "ingredient":
        normalized = _normalize_ingredient_style(normalized)
    if text_kind == "instruction":
        normalized = normalized.replace("Apprécier!", "Bon appétit !")
        normalized = normalized.replace("Apprécier !", "Bon appétit !")

    return normalized


def _replace_unit_match(match: re.Match[str]) -> str:
    quantity_text = match.group("quantity")
    unit_text = match.group("unit").lower()
    target_unit, multiplier = UNIT_CONVERSIONS[unit_text]

    if "-" in quantity_text:
        start_text, end_text = [part.strip() for part in quantity_text.split("-", maxsplit=1)]
        start_value = _parse_quantity(start_text)
        end_value = _parse_quantity(end_text)
        if start_value is None or end_value is None:
            return match.group(0)
        start_converted = _format_quantity(start_value * multiplier, target_unit)
        end_converted = _format_quantity(end_value * multiplier, target_unit)
        return f"{start_converted}-{end_converted} {target_unit}"

    quantity = _parse_quantity(quantity_text)
    if quantity is None:
        return match.group(0)

    converted = _format_quantity(quantity * multiplier, target_unit)
    return f"{converted} {target_unit}"


def _replace_fahrenheit_match(match: re.Match[str]) -> str:
    fahrenheit = int(match.group("temp"))
    celsius = round((fahrenheit - 32) * 5 / 9)
    return f"{celsius}°C"


def _replace_bare_temperature_match(match: re.Match[str]) -> str:
    return f"{match.group('temp')}°C"


def _parse_quantity(text: str) -> float | None:
    candidate = text.strip().replace(",", ".")
    candidate = re.sub(rf"(\d)([{FRACTION_CHARS}])", r"\1 \2", candidate)
    if candidate in FRACTION_MAP:
        return FRACTION_MAP[candidate]
    if "/" in candidate and " " not in candidate:
        try:
            numerator, denominator = candidate.split("/", maxsplit=1)
            return float(numerator) / float(denominator)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    parts = candidate.split()
    if len(parts) == 2 and parts[1] in FRACTION_MAP:
        try:
            return float(parts[0]) + FRACTION_MAP[parts[1]]
        except ValueError:
            return None
    try:
        return float(candidate)
    except ValueError:
        return None


def _format_quantity(value: float, unit: str) -> str:
    rounded = _round_for_unit(value, unit)
    if math.isclose(rounded, round(rounded), abs_tol=0.01):
        return str(int(round(rounded)))
    return f"{rounded:.1f}".rstrip("0").rstrip(".")


def _round_for_unit(value: float, unit: str) -> float:
    if unit in {"g", "ml"}:
        if value >= 100:
            return round(value / 5) * 5
        if value >= 20:
            return round(value)
        return round(value * 2) / 2
    if unit == "cm":
        return round(value, 1)
    return round(value, 1)


def _apply_french_glossary(text: str) -> str:
    result = text
    for source, target in sorted(FRENCH_GLOSSARY.items(), key=lambda item: len(item[0]), reverse=True):
        result = re.sub(rf"\b{re.escape(source)}\b", target, result, flags=re.IGNORECASE)
    return result


def _normalize_ingredient_style(text: str) -> str:
    normalized = text
    normalized = re.sub(r"\bml de? (?=(sel|poivre noir|origan|basilic|eau)\b)", "ml de ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bgousse ail\b", "gousse d'ail", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bde huile d'olive\b", "d'huile d'olive", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bde ail\b", "d'ail", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bde origan\b", "d'origan", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bde eau\b", "d'eau", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bde fleurons de brocoli\b", "de fleurons de brocoli", normalized, flags=re.IGNORECASE)
    normalized = normalized.replace("  ", " ").strip()
    return normalized
