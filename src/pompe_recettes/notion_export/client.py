from __future__ import annotations

from dataclasses import asdict
from typing import Any

import requests

from pompe_recettes.markdown import render_markdown
from pompe_recettes.models import Recipe
from pompe_recettes.notion_export.types import NotionPropertyMapping


NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"
MAX_RICH_TEXT_LENGTH = 2000
MAX_BLOCKS_PER_REQUEST = 100


class NotionClient:
    def __init__(
        self,
        token: str,
        notion_version: str = NOTION_VERSION,
        timeout: int = 30,
    ) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": notion_version,
                "Content-Type": "application/json",
            }
        )

    def retrieve_data_source(self, data_source_id: str) -> dict[str, Any]:
        return self._request("GET", f"/data_sources/{data_source_id}")

    def retrieve_database(self, database_id: str) -> dict[str, Any]:
        return self._request("GET", f"/databases/{database_id}")

    def create_page(
        self,
        parent_id: str,
        properties: dict[str, Any],
        children: list[dict[str, Any]] | None = None,
        parent_type: str = "data_source_id",
        cover: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "parent": {"type": parent_type, parent_type: parent_id},
            "properties": properties,
        }
        if cover:
            payload["cover"] = cover
        if children:
            payload["children"] = children[:MAX_BLOCKS_PER_REQUEST]
        return self._request("POST", "/pages", json=payload)

    def append_block_children(
        self,
        block_id: str,
        children: list[dict[str, Any]],
    ) -> None:
        for chunk in _chunked(children, MAX_BLOCKS_PER_REQUEST):
            self._request(
                "PATCH",
                f"/blocks/{block_id}/children",
                json={"children": chunk},
            )

    def query_data_source(
        self,
        data_source_id: str,
        filter_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/data_sources/{data_source_id}/query",
            json={"filter": filter_payload, "page_size": 1},
        )

    def query_database(
        self,
        database_id: str,
        filter_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/databases/{database_id}/query",
            json={"filter": filter_payload, "page_size": 1},
        )

    def _request(self, method: str, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.request(
            method,
            f"{NOTION_BASE_URL}{path}",
            json=json,
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            details = _safe_json(response)
            if response.status_code == 404 and isinstance(details, dict):
                message = details.get("message", "")
                if "shared with your integration" in message:
                    raise RuntimeError(
                        "Notion ne trouve pas cette database ou elle n'est pas partagee "
                        "avec l'integration. Ouvre la database dans Notion, puis "
                        "Share/Partager -> Connections et ajoute l'integration mentionnee."
                    ) from exc
            raise RuntimeError(
                f"Notion API error {response.status_code} on {path}: {details}"
            ) from exc
        return response.json()


class NotionRecipeExporter:
    def __init__(
        self,
        client: NotionClient,
        mapping: NotionPropertyMapping | None = None,
    ) -> None:
        self.client = client
        self.mapping = mapping or NotionPropertyMapping()

    def export_recipe(
        self,
        parent_id: str,
        recipe: Recipe,
        include_markdown_block: bool = False,
        parent_type: str = "data_source_id",
        schema_properties: dict[str, Any] | None = None,
        use_recipe_image_as_cover: bool = True,
    ) -> dict[str, Any]:
        if schema_properties is None:
            if parent_type == "data_source_id":
                schema_source = self.client.retrieve_data_source(parent_id)
            else:
                schema_source = self.client.retrieve_database(parent_id)
            schema_properties = schema_source.get("properties", {})

        existing_page = self.find_existing_recipe_page(
            parent_type=parent_type,
            parent_id=parent_id,
            recipe=recipe,
            schema_properties=schema_properties,
        )
        if existing_page is not None:
            return existing_page

        properties = build_notion_properties(
            recipe=recipe,
            data_source_properties=schema_properties,
            mapping=self.mapping,
            skip_image_property=use_recipe_image_as_cover,
        )
        children = build_recipe_blocks(recipe, include_markdown_block=include_markdown_block)
        cover = build_page_cover(recipe.image) if use_recipe_image_as_cover else None
        page = self.client.create_page(
            parent_id=parent_id,
            properties=properties,
            children=children[:MAX_BLOCKS_PER_REQUEST],
            parent_type=parent_type,
            cover=cover,
        )
        remaining_children = children[MAX_BLOCKS_PER_REQUEST:]
        if remaining_children:
            self.client.append_block_children(page["id"], remaining_children)
        return page

    def find_existing_recipe_page(
        self,
        *,
        parent_type: str,
        parent_id: str,
        recipe: Recipe,
        schema_properties: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not recipe.source_url:
            return None

        source_property_name = _find_source_url_property_name(
            data_source_properties=schema_properties,
            mapping=self.mapping,
        )
        if not source_property_name:
            return None

        property_schema = schema_properties.get(source_property_name, {})
        filter_payload = _build_source_url_filter(
            property_name=source_property_name,
            property_schema=property_schema,
            source_url=recipe.source_url,
        )
        if filter_payload is None:
            return None

        if parent_type == "data_source_id":
            result = self.client.query_data_source(parent_id, filter_payload)
        else:
            result = self.client.query_database(parent_id, filter_payload)

        results = result.get("results", [])
        return results[0] if results else None

    def resolve_parent(
        self,
        *,
        data_source_id: str = "",
        database_id: str = "",
    ) -> tuple[str, str, dict[str, Any]]:
        if data_source_id:
            data_source = self.client.retrieve_data_source(data_source_id)
            return "data_source_id", data_source_id, data_source.get("properties", {})
        if not database_id:
            raise RuntimeError("Aucun data_source_id ou database_id fourni pour Notion.")

        database = self.client.retrieve_database(database_id)
        data_sources = database.get("data_sources", [])
        if not data_sources:
            properties = database.get("properties", {})
            if properties:
                return "database_id", database_id, properties
            raise RuntimeError(
                "La database Notion est accessible, mais l'API ne renvoie ni data source "
                "ni schema de proprietes exploitable. Verifie les permissions de "
                "l'integration et la structure de la base."
            )
        data_source_id = data_sources[0]["id"]
        data_source = self.client.retrieve_data_source(data_source_id)
        return "data_source_id", data_source_id, data_source.get("properties", {})


def build_notion_properties(
    recipe: Recipe,
    data_source_properties: dict[str, Any],
    mapping: NotionPropertyMapping,
    skip_image_property: bool = False,
) -> dict[str, Any]:
    resolved_mapping = _resolve_mapping(data_source_properties, mapping)
    recipe_values = {
        "title": recipe.title,
        "description": recipe.description,
        "source_url": recipe.source_url,
        "author": recipe.author,
        "yields": recipe.yields,
        "total_time": _format_minutes(recipe.total_time),
        "prep_time": _format_minutes(recipe.prep_time),
        "cook_time": _format_minutes(recipe.cook_time),
        "image": recipe.image,
        "site_name": recipe.site_name,
    }

    properties: dict[str, Any] = {}
    for recipe_field, property_name in asdict(resolved_mapping).items():
        if skip_image_property and recipe_field == "image":
            continue
        if not property_name:
            continue
        raw_value = recipe_values.get(recipe_field)
        if raw_value in (None, "", []):
            continue
        property_schema = data_source_properties.get(property_name)
        if not property_schema:
            continue
        property_value = _build_property_value(property_schema, raw_value)
        if property_value is not None:
            properties[property_name] = property_value

    # Notion requires the actual title property of the database/schema.
    # If the configured mapping points to a non-title column, force the recipe
    # name into the real title property so the created page has the right name.
    title_property_name = _find_title_property_name(data_source_properties)
    if title_property_name and recipe.title:
        properties[title_property_name] = {
            "title": build_rich_text(recipe.title),
        }

    source_property_name = _find_source_url_property_name(
        data_source_properties=data_source_properties,
        mapping=mapping,
    )
    if source_property_name and recipe.source_url:
        source_schema = data_source_properties.get(source_property_name, {})
        source_property_value = _build_property_value(source_schema, recipe.source_url)
        if source_property_value is not None:
            properties[source_property_name] = source_property_value

    if not properties:
        raise RuntimeError(
            "Aucune propriete Notion exploitable trouvee. "
            "Verifie le data_source_id ou fournis un mapping explicite."
        )
    return properties


def build_page_cover(image_url: str | None) -> dict[str, Any] | None:
    if not image_url:
        return None
    if not image_url.startswith("https://"):
        return None
    return {
        "type": "external",
        "external": {
            "url": image_url,
        },
    }


def build_recipe_blocks(recipe: Recipe, include_markdown_block: bool = False) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    if recipe.description:
        blocks.append(paragraph_block(recipe.description))

    blocks.append(heading_block("Ingrédients", level=2))
    blocks.extend(bulleted_list_block(item) for item in recipe.ingredients if item.strip())

    blocks.append(heading_block("Étapes", level=2))
    blocks.extend(numbered_list_block(step) for step in recipe.instructions if step.strip())

    blocks.append(heading_block("Source", level=2))
    blocks.append(paragraph_block(recipe.source_url, link=recipe.source_url))

    if include_markdown_block:
        blocks.append(heading_block("Markdown", level=2))
        blocks.append(code_block(render_markdown(recipe), language="markdown"))

    return blocks


def paragraph_block(text: str, link: str | None = None) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": build_rich_text(text, link=link)},
    }


def heading_block(text: str, level: int = 2) -> dict[str, Any]:
    block_type = f"heading_{level}"
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": build_rich_text(text)},
    }


def bulleted_list_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": build_rich_text(text)},
    }


def numbered_list_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": build_rich_text(text)},
    }


def code_block(text: str, language: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "code",
        "code": {"language": language, "rich_text": build_rich_text(text)},
    }


def build_rich_text(text: str, link: str | None = None) -> list[dict[str, Any]]:
    chunks = []
    for chunk in _split_text(text, MAX_RICH_TEXT_LENGTH):
        text_payload: dict[str, Any] = {"content": chunk}
        if link:
            text_payload["link"] = {"url": link}
        chunks.append({"type": "text", "text": text_payload})
    return chunks


def _build_property_value(property_schema: dict[str, Any], raw_value: str) -> dict[str, Any] | None:
    property_type = property_schema.get("type")
    if property_type == "title":
        return {"title": build_rich_text(raw_value)}
    if property_type == "rich_text":
        return {"rich_text": build_rich_text(raw_value)}
    if property_type == "url":
        return {"url": raw_value}
    if property_type == "number":
        numeric_value = _parse_number(raw_value)
        return {"number": numeric_value} if numeric_value is not None else None
    if property_type == "select":
        return {"select": {"name": raw_value[:100]}}
    if property_type == "multi_select":
        values = [part.strip() for part in raw_value.split(",") if part.strip()]
        return {"multi_select": [{"name": value[:100]} for value in values]}
    return None


def _resolve_mapping(
    data_source_properties: dict[str, Any],
    mapping: NotionPropertyMapping,
) -> NotionPropertyMapping:
    aliases = {
        "title": ["name", "nom", "title", "titre", "recipe", "recette"],
        "description": ["description", "summary", "resume", "notes"],
        "source_url": ["source", "url", "link", "lien", "source url"],
        "author": ["author", "auteur"],
        "yields": ["yield", "yields", "servings", "portions"],
        "total_time": ["total time", "temps total", "time", "duration"],
        "prep_time": ["prep time", "preparation", "temps de preparation", "préparation"],
        "cook_time": ["cook time", "cuisson", "temps de cuisson"],
        "image": ["image", "photo", "cover", "illustration"],
        "site_name": ["site", "source site", "website"],
    }

    resolved = asdict(mapping)
    available = {
        property_name: _normalize_name(property_name)
        for property_name in data_source_properties.keys()
    }

    for field_name, property_name in resolved.items():
        if property_name:
            continue
        for alias in aliases[field_name]:
            for candidate_name, normalized_candidate in available.items():
                if normalized_candidate == _normalize_name(alias):
                    resolved[field_name] = candidate_name
                    break
            if resolved[field_name]:
                break

    return NotionPropertyMapping(**resolved)


def _find_title_property_name(data_source_properties: dict[str, Any]) -> str | None:
    for property_name, property_schema in data_source_properties.items():
        if property_schema.get("type") == "title":
            return property_name
    return None


def _find_source_url_property_name(
    data_source_properties: dict[str, Any],
    mapping: NotionPropertyMapping,
) -> str | None:
    if mapping.source_url and mapping.source_url in data_source_properties:
        return mapping.source_url

    resolved_mapping = _resolve_mapping(data_source_properties, mapping)
    if resolved_mapping.source_url and resolved_mapping.source_url in data_source_properties:
        return resolved_mapping.source_url

    for property_name, property_schema in data_source_properties.items():
        normalized_name = _normalize_name(property_name)
        if property_schema.get("type") in {"url", "rich_text"} and normalized_name in {
            "source",
            "sourceurl",
            "url",
            "link",
            "lien",
            "recipelink",
        }:
            return property_name
    return None


def _build_source_url_filter(
    property_name: str,
    property_schema: dict[str, Any],
    source_url: str,
) -> dict[str, Any] | None:
    property_type = property_schema.get("type")
    if property_type == "url":
        return {
            "property": property_name,
            "url": {"equals": source_url},
        }
    if property_type == "rich_text":
        return {
            "property": property_name,
            "rich_text": {"equals": source_url},
        }
    return None


def _normalize_name(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _parse_number(value: str) -> float | None:
    digits = "".join(character for character in value if character.isdigit() or character in ",.-")
    if not digits:
        return None
    try:
        return float(digits.replace(",", "."))
    except ValueError:
        return None


def _format_minutes(value: int | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _split_text(text: str, max_length: int) -> list[str]:
    if len(text) <= max_length:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + max_length])
        start += max_length
    return chunks


def _chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
