from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from pompe_recettes.notion_export.client import NOTION_VERSION, NotionClient, NotionRecipeExporter
from pompe_recettes.notion_export.types import NotionPropertyMapping


DEFAULT_CONFIG_PATH = Path("config/notion.toml")


@dataclass(slots=True)
class NotionConfig:
    token_env: str
    data_source_id: str = ""
    database_id: str = ""
    database_url: str = ""
    notion_version: str = NOTION_VERSION
    include_markdown_block: bool = False
    use_recipe_image_as_cover: bool = True
    properties: NotionPropertyMapping = field(default_factory=NotionPropertyMapping)

    def read_token(self) -> str:
        token = os.getenv(self.token_env)
        if not token:
            raise RuntimeError(
                f"Variable d'environnement manquante: {self.token_env}. "
                "Definis-la avant d'utiliser l'export Notion."
            )
        return token


def load_notion_config(path: str | Path = DEFAULT_CONFIG_PATH) -> NotionConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise RuntimeError(
            f"Fichier de config Notion introuvable: {config_path}. "
            "Cree-le ou adapte le chemin de config."
        )

    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    # Accept both the legacy dedicated notion config shape and the new global
    # project config shape with a nested [notion] table.
    if "notion" in raw and isinstance(raw["notion"], dict):
        raw = raw["notion"]

    properties = NotionPropertyMapping(**raw.get("properties", {}))
    return NotionConfig(
        token_env=raw.get("token_env", "NOTION_TOKEN"),
        data_source_id=raw.get("data_source_id", ""),
        database_id=raw.get("database_id", ""),
        database_url=raw.get("database_url", ""),
        notion_version=raw.get("notion_version", NOTION_VERSION),
        include_markdown_block=bool(raw.get("include_markdown_block", False)),
        use_recipe_image_as_cover=bool(raw.get("use_recipe_image_as_cover", True)),
        properties=properties,
    )


def build_exporter_from_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[NotionConfig, NotionRecipeExporter]:
    config = load_notion_config(path)
    client = NotionClient(
        token=config.read_token(),
        notion_version=config.notion_version,
    )
    exporter = NotionRecipeExporter(client, mapping=config.properties)
    return config, exporter


def extract_notion_id(value: str) -> str:
    match = re.search(r"([0-9a-fA-F]{32})", value)
    if not match:
        raise RuntimeError(f"Impossible d'extraire un identifiant Notion valide depuis: {value}")
    return match.group(1)
