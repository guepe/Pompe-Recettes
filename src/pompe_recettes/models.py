from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Recipe:
    title: str
    source_url: str
    author: str | None = None
    description: str | None = None
    yields: str | None = None
    total_time: int | None = None
    prep_time: int | None = None
    cook_time: int | None = None
    image: str | None = None
    ingredients: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    site_name: str | None = None
