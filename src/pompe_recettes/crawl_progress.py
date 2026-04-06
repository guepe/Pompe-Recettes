from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pompe_recettes.models import Recipe


@dataclass(slots=True)
class CrawlCheckpoint:
    start_url: str
    queue: list[str] = field(default_factory=list)
    seen_urls: list[str] = field(default_factory=list)
    recipe_urls: list[str] = field(default_factory=list)
    recipes: list[dict[str, Any]] = field(default_factory=list)
    served_recipes: int = 0
    crawled_pages: int = 0


class CrawlProgressStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self, start_url: str) -> CrawlCheckpoint | None:
        payload = self._load_all()
        raw_entry = payload.get(start_url)
        if not isinstance(raw_entry, dict):
            return None

        recipe_payloads = _coerce_recipe_payloads(raw_entry.get("recipes"))
        served_recipes = raw_entry.get("served_recipes")
        if served_recipes is None:
            served_recipes = len(recipe_payloads)

        return CrawlCheckpoint(
            start_url=start_url,
            queue=_coerce_str_list(raw_entry.get("queue")),
            seen_urls=_coerce_str_list(raw_entry.get("seen_urls")),
            recipe_urls=_coerce_str_list(raw_entry.get("recipe_urls")),
            recipes=recipe_payloads,
            served_recipes=_coerce_int(served_recipes),
            crawled_pages=_coerce_int(raw_entry.get("crawled_pages")),
        )

    def save(self, checkpoint: CrawlCheckpoint) -> None:
        payload = self._load_all()
        payload[checkpoint.start_url] = asdict(checkpoint)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_recipes(self, start_url: str) -> list[Recipe]:
        checkpoint = self.load(start_url)
        if checkpoint is None:
            return []
        return [recipe_from_dict(raw_recipe) for raw_recipe in checkpoint.recipes]

    def _load_all(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}

        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}


def recipe_from_dict(payload: dict[str, Any]) -> Recipe:
    return Recipe(
        title=str(payload.get("title") or "Recette sans titre"),
        source_url=str(payload.get("source_url") or ""),
        author=_coerce_optional_text(payload.get("author")),
        description=_coerce_optional_text(payload.get("description")),
        yields=_coerce_optional_text(payload.get("yields")),
        total_time=_coerce_optional_int(payload.get("total_time")),
        prep_time=_coerce_optional_int(payload.get("prep_time")),
        cook_time=_coerce_optional_int(payload.get("cook_time")),
        image=_coerce_optional_text(payload.get("image")),
        ingredients=_coerce_str_list(payload.get("ingredients")),
        instructions=_coerce_str_list(payload.get("instructions")),
        site_name=_coerce_optional_text(payload.get("site_name")),
    )


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _coerce_recipe_payloads(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    payloads: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            payloads.append(item)
    return payloads


def _coerce_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _coerce_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
