from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from pompe_recettes.models import Recipe


def extract_site_recipe(url: str, html: str) -> Recipe | None:
    host = urlparse(url).netloc.replace("www.", "")
    if host == "colruyt.be":
        return extract_colruyt_recipe(url, html)
    if host == "sofiedumont.fr":
        return extract_sofiedumont_recipe(url, html)
    if host == "visitwallonia.be":
        return extract_visitwallonia_recipe(url, html)
    if host == "giallozafferano.com":
        return extract_giallozafferano_recipe(url, html)
    if host == "katieparla.com":
        return extract_katieparla_recipe(url, html)
    if host == "equifrais.be":
        return extract_equifrais_recipe(url, html)
    return None


def find_site_candidate_links(url: str, html: str) -> list[str]:
    host = urlparse(url).netloc.replace("www.", "")
    if host == "giallozafferano.com":
        return find_giallozafferano_links(url, html)
    if host == "sofiedumont.fr":
        return find_sofiedumont_links(url, html)
    if host == "visitwallonia.be":
        return find_visitwallonia_links(url, html)
    if host == "equifrais.be":
        return find_equifrais_links(url, html)
    return []


def extract_colruyt_recipe(url: str, html: str) -> Recipe | None:
    return extract_recipe_from_ld_json(url, html, site_name="colruyt.be")


def extract_sofiedumont_recipe(url: str, html: str) -> Recipe | None:
    return extract_recipe_from_ld_json(url, html, site_name="sofiedumont.fr")


def extract_giallozafferano_recipe(url: str, html: str) -> Recipe | None:
    return extract_recipe_from_ld_json(url, html, site_name="giallozafferano.com")


def find_giallozafferano_links(base_url: str, html: str) -> list[str]:
    parsed = urlparse(base_url)
    if "/recipes-list/" not in parsed.path:
        return []

    soup = BeautifulSoup(html, "html.parser")
    item_list_links = _extract_item_list_links(soup, base_url)
    pagination_links = _extract_same_listing_pagination_links(soup, base_url)

    if item_list_links:
        return _deduplicate_preserve_order(item_list_links + pagination_links)

    # Fallback for listing pages without usable ItemList schema.
    listing_root = _giallo_listing_root(parsed.path)
    links: list[str] = []
    for anchor in soup.select('a[href*="/recipes/"], a[href*="/recipes-list/"]'):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        absolute_url = urljoin(base_url, href)
        absolute_parsed = urlparse(absolute_url)
        if absolute_parsed.netloc != parsed.netloc:
            continue
        normalized = absolute_parsed._replace(query="", fragment="").geturl()
        if absolute_parsed.path.startswith("/recipes/"):
            links.append(normalized)
            continue
        if _is_same_giallo_listing_page(absolute_parsed.path, listing_root):
            links.append(normalized)

    return _deduplicate_preserve_order(links)


def extract_recipe_from_ld_json(url: str, html: str, site_name: str) -> Recipe | None:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.select('script[type="application/ld+json"]'):
        payload = _load_json(script.string or script.get_text())
        recipe_data = _find_recipe_payload(payload)
        if recipe_data is None:
            continue
        recipe = _recipe_from_ld_json(url, recipe_data, site_name=site_name)
        if recipe is not None:
            return recipe
    return None


def extract_visitwallonia_recipe(url: str, html: str) -> Recipe | None:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article.node.node-page-contenu")
    if article is None:
        return None

    title_node = soup.select_one("h1.header--banner--title")
    title = _text(title_node.get_text(" ", strip=True)) if title_node else None

    description = _extract_visitwallonia_description(article)
    image = None
    image_node = soup.select_one(".header--banner--picture img")
    if image_node is not None:
        image = _normalize_image_url(url, image_node.get("src"))

    prep_time, yields = _extract_visitwallonia_meta(article)
    ingredients = _extract_visitwallonia_list(article, "Ce qu'il vous faut", "ul")
    instructions = _extract_visitwallonia_list(article, "À vous de jouer", "ol")

    if not title or not ingredients or not instructions:
        return None

    author = "Julien Lapraille" if description and "Julien Lapraille" in description else None
    return Recipe(
        title=title,
        source_url=url,
        author=author,
        description=description,
        yields=yields,
        total_time=prep_time,
        prep_time=prep_time,
        image=image,
        ingredients=ingredients,
        instructions=instructions,
        site_name="visitwallonia.be",
    )


def extract_katieparla_recipe(url: str, html: str) -> Recipe | None:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one(".blog-single-content")
    if content is None:
        return None

    title = _extract_katie_title(soup)
    ingredients_heading = content.find(
        lambda tag: tag.name == "p" and _clean_katie_text(tag.get_text(" ", strip=True)) == "Ingredients"
    )
    if ingredients_heading is None:
        return None

    ingredients: list[str] = []
    instructions: list[str] = []
    current_heading: str | None = None

    for sibling in ingredients_heading.next_siblings:
        if not isinstance(sibling, Tag):
            continue
        if sibling.name in {"h2", "h3"}:
            break

        text = _clean_katie_text(sibling.get_text(" ", strip=True))
        if not text:
            continue

        if sibling.name == "ul":
            items = [
                _clean_katie_text(item.get_text(" ", strip=True))
                for item in sibling.select("li")
                if _clean_katie_text(item.get_text(" ", strip=True))
            ]
            if not ingredients:
                ingredients = items
            elif current_heading:
                instructions.extend(f"{current_heading}: {item}" for item in items)
            else:
                instructions.extend(items)
            continue

        if sibling.name == "p":
            lowered = text.lower().rstrip(":")
            if lowered in {"share this post", "categories"}:
                break
            current_heading = text.rstrip(":")

    if not title or not ingredients or not instructions:
        return None

    description = _extract_meta_content(soup, "name", "description")
    image = _extract_meta_content(soup, "property", "og:image")
    author = None
    article_payload = _extract_article_payload(soup)
    if article_payload is not None:
        author_value = article_payload.get("author")
        if isinstance(author_value, dict):
            author = _text(author_value.get("name"))
        else:
            author = _text(author_value)

    return Recipe(
        title=title,
        source_url=url,
        author=author,
        description=description,
        image=image,
        ingredients=ingredients,
        instructions=instructions,
        site_name="katieparla.com",
    )


def find_sofiedumont_links(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = [
        urljoin(base_url, anchor.get("href", "").strip())
        for anchor in soup.select('a[href*="/pages/recette-"]')
        if anchor.get("href", "").strip()
    ]
    return _deduplicate_preserve_order(links)


def find_visitwallonia_links(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []

    for anchor in soup.select('a[href^="/node/"], a[href*="/content/recette-de-cuisine-"]'):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        links.append(urljoin(base_url, href))

    return _deduplicate_preserve_order(links)


def _recipe_from_ld_json(url: str, payload: dict[str, Any], site_name: str) -> Recipe | None:
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
        first_image = image[0] if image else None
        if isinstance(first_image, dict):
            image_text = _text(first_image.get("url")) or _text(first_image.get("@id"))
        else:
            image_text = _text(first_image)
    elif isinstance(image, dict):
        image_text = _text(image.get("url")) or _text(image.get("@id"))
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
        image=_normalize_image_url(url, image_text),
        ingredients=ingredients,
        instructions=[step for step in instructions if step],
        site_name=site_name,
    )


def extract_equifrais_recipe(url: str, html: str) -> Recipe | None:
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.select_one("h1.text-script")
    title = _text(title_node.get_text(" ", strip=True)) if title_node else None

    ingredient_section = soup.find("h6", string=lambda value: value and "Ingrédients" in value)
    ingredients = _extract_list_after_heading(ingredient_section)

    prep_card = None
    for card in soup.select(".card"):
        card_text = " ".join(card.get_text(" ", strip=True).split())
        if "Préparation" in card_text:
            prep_card = card_text
            break

    prep_time = _extract_equifrais_prep_time(prep_card or "")
    image = _extract_equifrais_image(html)

    if not title or not ingredients:
        return None

    return Recipe(
        title=title,
        source_url=url,
        prep_time=prep_time,
        total_time=prep_time,
        image=image,
        ingredients=ingredients,
        instructions=[],
        site_name="equifrais.be",
    )


def find_equifrais_links(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for anchor in soup.select("a.meal-li[href]"):
        href = anchor.get("href", "").strip()
        if href:
            links.append(urljoin(base_url, href))
    return _deduplicate_preserve_order(links)


def _extract_visitwallonia_description(article: Any) -> str | None:
    node = article.select_one(".field-item.even > p strong")
    if node is None:
        return None
    return _text(node.get_text(" ", strip=True))


def _extract_visitwallonia_meta(article: Any) -> tuple[int | None, str | None]:
    node = article.find(string=lambda value: value and "Préparation" in value)
    if node is None:
        text = article.get_text(" ", strip=True)
    else:
        paragraph = node.find_parent("p") if hasattr(node, "find_parent") else None
        source = paragraph or getattr(node, "parent", None)
        text = source.get_text(" ", strip=True) if source is not None else str(node)

    prep_match = re.search(r"Préparation\s*:\s*(\d+)", text)
    yields_match = re.search(r"(\d+)\s*(?:parts?|personnes|portions?)", text, re.IGNORECASE)

    prep_time = int(prep_match.group(1)) if prep_match else None
    yields = f"{yields_match.group(1)} parts" if yields_match else None
    return prep_time, yields


def _extract_visitwallonia_list(article: Any, heading_label: str, list_tag: str) -> list[str]:
    heading = article.find(
        lambda tag: tag.name == "h2" and heading_label.lower() in tag.get_text(" ", strip=True).lower()
    )
    if heading is None:
        return []

    for sibling in heading.next_siblings:
        if not hasattr(sibling, "name"):
            continue
        if sibling.name == list_tag:
            items = [
                _text(" ".join(item.get_text(" ", strip=True).split()))
                for item in sibling.select("li")
            ]
            return [item for item in items if item]
        if sibling.name == "h2":
            break
    return []


def _extract_katie_title(soup: BeautifulSoup) -> str | None:
    for heading in soup.select("h1"):
        text = _text(heading.get_text(" ", strip=True))
        if text and text.lower() != "katie parla":
            return text

    title = _extract_meta_content(soup, "property", "og:title")
    if title:
        return re.sub(r"\s*\|\s*Katie Parla\s*$", "", title).strip()
    return None


def _extract_article_payload(soup: BeautifulSoup) -> dict[str, Any] | None:
    for script in soup.select('script[type="application/ld+json"]'):
        payload = _load_json(script.string or script.get_text())
        if not payload:
            continue
        article = _find_article_payload(payload)
        if article is not None:
            return article
    return None


def _extract_item_list_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    links: list[str] = []
    for script in soup.select('script[type="application/ld+json"]'):
        payload = _load_json(script.string or script.get_text())
        links.extend(_find_item_list_links(payload, base_url))
    return _deduplicate_preserve_order(links)


def _find_item_list_links(payload: Any, base_url: str) -> list[str]:
    if isinstance(payload, dict):
        payload_type = payload.get("@type")
        if payload_type == "ItemList" or (
            isinstance(payload_type, list) and "ItemList" in payload_type
        ):
            return _extract_urls_from_item_list(payload, base_url)
        links: list[str] = []
        for value in payload.values():
            links.extend(_find_item_list_links(value, base_url))
        return links
    if isinstance(payload, list):
        links: list[str] = []
        for item in payload:
            links.extend(_find_item_list_links(item, base_url))
        return links
    return []


def _extract_urls_from_item_list(payload: dict[str, Any], base_url: str) -> list[str]:
    items = payload.get("itemListElement")
    if not isinstance(items, list):
        return []

    links: list[str] = []
    for item in items:
        url = None
        if isinstance(item, dict):
            nested_item = item.get("item")
            if isinstance(nested_item, dict):
                url = _text(nested_item.get("@id")) or _text(nested_item.get("url"))
            else:
                url = _text(nested_item)
            url = url or _text(item.get("url"))
        else:
            url = _text(item)

        if not url:
            continue
        absolute_url = urljoin(base_url, url)
        parsed = urlparse(absolute_url)
        if parsed.path.startswith("/recipes/"):
            links.append(parsed._replace(query="", fragment="").geturl())

    return links


def _extract_same_listing_pagination_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    listing_root = _giallo_listing_root(parsed.path)
    links: list[str] = []

    for anchor in soup.select('a[href*="/recipes-list/"]'):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        absolute_url = urljoin(base_url, href)
        absolute_parsed = urlparse(absolute_url)
        if absolute_parsed.netloc != parsed.netloc:
            continue
        if _is_same_giallo_listing_page(absolute_parsed.path, listing_root):
            links.append(absolute_parsed._replace(query="", fragment="").geturl())

    return _deduplicate_preserve_order(links)


def _giallo_listing_root(path: str) -> str:
    normalized_path = path.rstrip("/")
    page_match = re.match(r"^(.*?/recipes-list/[^/]+)/page\d+$", normalized_path)
    if page_match:
        return page_match.group(1)
    return normalized_path


def _is_same_giallo_listing_page(path: str, listing_root: str) -> bool:
    normalized_path = path.rstrip("/")
    if normalized_path == listing_root:
        return True
    return bool(re.match(rf"^{re.escape(listing_root)}/page\d+$", normalized_path))


def _find_article_payload(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        payload_type = payload.get("@type")
        if isinstance(payload_type, list) and (
            "Article" in payload_type or "BlogPosting" in payload_type
        ):
            return payload
        if payload_type in {"Article", "BlogPosting"}:
            return payload
        for value in payload.values():
            article = _find_article_payload(value)
            if article is not None:
                return article
    if isinstance(payload, list):
        for item in payload:
            article = _find_article_payload(item)
            if article is not None:
                return article
    return None


def _extract_meta_content(soup: BeautifulSoup, attr: str, value: str) -> str | None:
    node = soup.find("meta", attrs={attr: value})
    if node is None:
        return None
    return _text(node.get("content"))


def _clean_katie_text(value: str | None) -> str | None:
    text = _text(value)
    if text is None:
        return None
    return " ".join(text.split())


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


def _normalize_image_url(page_url: str, image_url: str | None) -> str | None:
    image_text = _text(image_url)
    if image_text is None:
        return None
    if image_text.startswith("//"):
        return f"https:{image_text}"
    if "/www.sofiedumont.fr/cdn/" in image_text:
        return "https://www.sofiedumont.fr/" + image_text.split(
            "/www.sofiedumont.fr/", maxsplit=1
        )[1].lstrip("/")
    if image_text.startswith("www.sofiedumont.fr/"):
        return f"https://{image_text}"

    if image_text.startswith("http://") or image_text.startswith("https://"):
        return image_text
    return urljoin(page_url, image_text)


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


def _extract_list_after_heading(heading_node: Any) -> list[str]:
    if heading_node is None:
        return []
    card = heading_node.find_parent(class_="card")
    if card is None:
        return []
    items = []
    for item in card.select("ul li"):
        text = item.get_text(" ", strip=True)
        if text:
            items.append(text)
    return items


def _extract_equifrais_prep_time(text: str) -> int | None:
    match = re.search(r"(\d+)\s*-\s*(\d+)'", text)
    if match:
        start = int(match.group(1))
        end = int(match.group(2))
        return round((start + end) / 2)
    match = re.search(r"(\d+)'", text)
    if match:
        return int(match.group(1))
    return None


def _extract_equifrais_image(html: str) -> str | None:
    match = re.search(
        r"background-image:\s*url\((https://www\.equifrais\.be/images/i_elements/meals/[^)]+)\)",
        html,
    )
    if match:
        return match.group(1)
    return None


def _deduplicate_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique
