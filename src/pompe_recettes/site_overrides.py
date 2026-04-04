from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from pompe_recettes.models import Recipe


def extract_site_recipe(url: str, html: str) -> Recipe | None:
    host = urlparse(url).netloc.replace("www.", "")
    if host == "colruyt.be":
        return extract_colruyt_recipe(url, html)
    return None


def extract_colruyt_recipe(url: str, html: str) -> Recipe | None:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.select('script[type="application/ld+json"]'):
        payload = _load_json(script.string or script.get_text())
        recipe_data = _find_recipe_payload(payload)
        if recipe_data is None:
            continue
        recipe = _recipe_from_ld_json(url, recipe_data)
        if recipe is not None:
            return recipe
    return None


def _recipe_from_ld_json(url: str, payload: dict[str, Any]) -> Recipe | None:
    title = _text(payload.get("name"))
    ingredients = _normalize_strings(payload.get("recipeIngredient"))
    instructions = _normalize_instructions(payload.get("recipeInstructions"))

    if not title or not ingredients:
        return None

    author = payload.get("author")
    if isinstance(author, dict):
        author_text = _text(author.get("name"))
    else:
        author_text = _text(author)

    image = payload.get("image")
    if isinstance(image, list):
        image_text = _text(image[0]) if image else None
    else:
        image_text = _text(image)

    return Recipe(
        title=title,
        source_url=url,
        author=author_text,
        description=_text(payload.get("description")),
        yields=_text(payload.get("recipeYield")),
        total_time=_duration_to_minutes(payload.get("totalTime")),
        prep_time=_duration_to_minutes(payload.get("prepTime")),
        cook_time=_duration_to_minutes(payload.get("cookTime")),
        image=image_text,
        ingredients=ingredients,
        instructions=[step for step in instructions if step],
        site_name="colruyt.be",
    )


def _find_recipe_payload(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        payload_type = payload.get("@type")
        if payload_type == "Recipe" or (
            isinstance(payload_type, list) and "Recipe" in payload_type
        ):
            return payload
        if "@graph" in payload:
            return _find_recipe_payload(payload["@graph"])
    if isinstance(payload, list):
        for item in payload:
            recipe_data = _find_recipe_payload(item)
            if recipe_data is not None:
                return recipe_data
    return None


def _normalize_instructions(value: Any) -> list[str]:
    if isinstance(value, str):
        return [line.strip() for line in value.split("\n") if line.strip()]
    if not isinstance(value, list):
        return []

    steps: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = _text(item.get("text")) or _text(item.get("name"))
        else:
            text = None
        if text:
            steps.append(text)
    return steps


def _normalize_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = _text(item)
        if text:
            normalized.append(text)
    return normalized


def _load_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _duration_to_minutes(value: Any) -> int | None:
    if not value or not isinstance(value, str):
        return None
    if not value.startswith("PT"):
        return None
    hours = 0
    minutes = 0
    raw = value[2:]
    if "H" in raw:
        hour_part, raw = raw.split("H", maxsplit=1)
        hours = int(hour_part or 0)
    if "M" in raw:
        minute_part = raw.split("M", maxsplit=1)[0]
        minutes = int(minute_part or 0)
    return hours * 60 + minutes
