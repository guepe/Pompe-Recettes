from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class NotionPropertyMapping:
    title: str | None = None
    description: str | None = None
    source_url: str | None = None
    author: str | None = None
    yields: str | None = None
    total_time: str | None = None
    prep_time: str | None = None
    cook_time: str | None = None
    image: str | None = None
    site_name: str | None = None
