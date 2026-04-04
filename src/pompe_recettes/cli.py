from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from recipe_scrapers._exceptions import WebsiteNotImplementedError
from recipe_scrapers import scrape_html

from pompe_recettes.fetcher import fetch_html
from pompe_recettes.localize import localize_recipe
from pompe_recettes.markdown import recipe_filename, render_markdown
from pompe_recettes.models import Recipe
from pompe_recettes.notion_export import (
    DEFAULT_CONFIG_PATH,
    build_exporter_from_config,
    extract_notion_id,
)
from pompe_recettes.project_config import DEFAULT_PROJECT_CONFIG_PATH, load_project_config
from pompe_recettes.site_overrides import extract_site_recipe


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pompe-recettes",
        description=(
            "Extrait une recette depuis une URL supportee et la convertit en Markdown "
            "pret a coller dans Notion."
        ),
    )
    parser.add_argument("url", nargs="?", help="URL de la recette a extraire")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_PROJECT_CONFIG_PATH),
        help="Chemin du fichier de configuration global du projet.",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Chemin du fichier Markdown de sortie. Si absent, imprime dans stdout.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=None,
        help="Affiche le JSON structure de la recette plutot que le Markdown.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Nombre maximum de pages a visiter quand l'URL fournie n'est pas une recette.",
    )
    parser.add_argument(
        "--max-recipes",
        type=int,
        default=None,
        help="Nombre maximum de recettes a retourner lors du crawling.",
    )
    parser.add_argument(
        "--translate-fr",
        action="store_true",
        default=None,
        help="Traduit le texte vers le francais et convertit les unites vers un format europeen.",
    )
    parser.add_argument(
        "--no-translate-fr",
        dest="translate_fr",
        action="store_false",
        help="Garde le texte source sans traduction francaise.",
    )
    parser.add_argument(
        "--output-dir",
        help="Dossier de sortie pour ecrire une recette Markdown par fichier.",
    )
    parser.add_argument(
        "--push-notion",
        action="store_true",
        default=None,
        help="Pousse les recettes vers Notion en utilisant la config locale.",
    )
    parser.add_argument(
        "--no-push-notion",
        dest="push_notion",
        action="store_false",
        help="N'envoie pas les recettes vers Notion.",
    )
    parser.add_argument(
        "--notion-config",
        default=None,
        help="Chemin du fichier de configuration Notion.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    project_config = load_project_config(args.config)
    run_config = project_config.run

    url = args.url or run_config.url
    if not url:
        print(
            "Erreur: aucune URL fournie. Passe une URL dans la CLI ou renseigne [run].url dans la config projet.",
            file=sys.stderr,
        )
        return 1

    max_pages = args.max_pages if args.max_pages is not None else run_config.max_pages
    max_recipes = args.max_recipes if args.max_recipes is not None else run_config.max_recipes
    translate_fr = (
        args.translate_fr if args.translate_fr is not None else run_config.translate_fr
    )
    push_notion = args.push_notion if args.push_notion is not None else run_config.push_notion
    output = args.output if args.output is not None else run_config.output
    output_dir = args.output_dir if args.output_dir is not None else run_config.output_dir
    emit_json = args.json if args.json is not None else run_config.json
    notion_config_path = args.notion_config or args.config or str(DEFAULT_CONFIG_PATH)

    try:
        recipes = collect_recipes(
            url,
            max_pages=max(1, max_pages),
            max_recipes=max(1, max_recipes),
        )
    except Exception as exc:  # pragma: no cover
        print(f"Erreur: impossible d'extraire la recette: {exc}", file=sys.stderr)
        return 1
    if not recipes:
        print(
            "Erreur: aucune recette exploitable trouvee a partir de cette URL.",
            file=sys.stderr,
        )
        return 1

    if translate_fr:
        recipes = [localize_recipe(recipe, translate_to_french=True) for recipe in recipes]

    if emit_json:
        payload: Any
        if len(recipes) == 1:
            payload = recipe_to_dict(recipes[0])
        else:
            payload = [recipe_to_dict(recipe) for recipe in recipes]
        content = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        content = render_recipes_markdown(recipes)

    if output and output_dir:
        print(
            "Erreur: utilise soit --output, soit --output-dir, pas les deux.",
            file=sys.stderr,
        )
        return 1

    if output_dir:
        write_recipe_files(recipes, Path(output_dir))
    elif output:
        with open(output, "w", encoding="utf-8") as handle:
            handle.write(content)
    else:
        print(content, end="" if content.endswith("\n") else "\n")

    if push_notion:
        push_results = push_recipes_to_notion(recipes, Path(notion_config_path))
        for result in push_results:
            print(f"Notion: {result}")

    return 0


def collect_recipes(url: str, max_pages: int, max_recipes: int) -> list[Recipe]:
    recipes: list[Recipe] = []
    seen_urls: set[str] = set()
    queued_urls: set[str] = {url}
    queue: deque[str] = deque([url])
    origin = urlparse(url)

    while queue and len(seen_urls) < max_pages and len(recipes) < max_recipes:
        current_url = queue.popleft()
        queued_urls.discard(current_url)
        if current_url in seen_urls:
            continue

        seen_urls.add(current_url)
        html = fetch_html(current_url)
        recipe = extract_recipe(current_url, html)
        if recipe is not None:
            recipes.append(recipe)
            continue

        for link in find_candidate_links(current_url, html, origin.netloc):
            if link not in seen_urls and link not in queued_urls:
                queue.append(link)
                queued_urls.add(link)

    return recipes


def extract_recipe(url: str, html: str) -> Recipe | None:
    override_recipe = extract_site_recipe(url, html)
    if override_recipe is not None and is_viable_recipe(override_recipe):
        return override_recipe

    try:
        scraper = scrape_html(html=html, org_url=url)
    except WebsiteNotImplementedError:
        return None

    recipe = to_recipe(url, scraper.to_json())
    if not is_viable_recipe(recipe):
        return None
    return recipe


def to_recipe(url: str, payload: dict[str, Any]) -> Recipe:
    site_name = urlparse(url).netloc.replace("www.", "")
    instructions = _normalize_instructions(
        payload.get("instructions_list") or payload.get("instructions")
    )
    ingredients = _normalize_ingredients(payload.get("ingredients"))

    return Recipe(
        title=_coerce_text(payload.get("title")) or "Recette sans titre",
        source_url=url,
        author=_coerce_text(payload.get("author")),
        description=_coerce_text(payload.get("description")),
        yields=_coerce_text(payload.get("yields")),
        total_time=_coerce_int(payload.get("total_time")),
        prep_time=_coerce_int(payload.get("prep_time")),
        cook_time=_coerce_int(payload.get("cook_time")),
        image=_coerce_text(payload.get("image")),
        ingredients=ingredients,
        instructions=instructions,
        site_name=site_name,
    )


def is_viable_recipe(recipe: Recipe) -> bool:
    if not recipe.title or recipe.title == "Recette sans titre":
        return False
    if len(recipe.ingredients) < 2:
        return False
    return bool(recipe.instructions) or recipe.total_time is not None or recipe.yields is not None


def find_candidate_links(base_url: str, html: str, allowed_host: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        absolute_url = urljoin(base_url, href)
        parsed = urlparse(absolute_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc != allowed_host:
            continue
        if parsed.path in {"", "/"}:
            continue
        if "/category/" in parsed.path:
            continue

        text = anchor.get_text(" ", strip=True).lower()
        if _looks_like_recipe_link(parsed.path, text):
            links.append(_normalize_url(absolute_url))

    return _deduplicate_preserve_order(links)


def render_recipes_markdown(recipes: list[Recipe]) -> str:
    if len(recipes) == 1:
        return render_markdown(recipes[0])
    parts = [render_markdown(recipe).strip() for recipe in recipes]
    return "\n\n---\n\n".join(parts) + "\n"


def write_recipe_files(recipes: list[Recipe], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    written_names: set[str] = set()

    for index, recipe in enumerate(recipes, start=1):
        base_name = recipe_filename(recipe)
        filename = _unique_filename(base_name, written_names, index)
        written_names.add(filename)
        target = output_dir / filename
        target.write_text(render_markdown(recipe), encoding="utf-8")


def push_recipes_to_notion(recipes: list[Recipe], config_path: Path) -> list[str]:
    config, exporter = build_exporter_from_config(config_path)
    parent_type, parent_id, schema_properties = exporter.resolve_parent(
        data_source_id=config.data_source_id,
        database_id=_resolve_database_id(config),
    )
    page_urls: list[str] = []

    for recipe in recipes:
        page = exporter.export_recipe(
            parent_id=parent_id,
            recipe=recipe,
            include_markdown_block=config.include_markdown_block,
            parent_type=parent_type,
            schema_properties=schema_properties,
            use_recipe_image_as_cover=config.use_recipe_image_as_cover,
        )
        page_urls.append(page.get("url", page.get("id", "page créée")))

    return page_urls


def _resolve_database_id(config: Any) -> str:
    if getattr(config, "database_id", ""):
        return config.database_id
    if getattr(config, "database_url", ""):
        return extract_notion_id(config.database_url)
    return ""


def _unique_filename(base_name: str, existing: set[str], index: int) -> str:
    if base_name not in existing:
        return base_name

    stem = Path(base_name).stem
    suffix = Path(base_name).suffix
    candidate = f"{stem}-{index}{suffix}"
    counter = index
    while candidate in existing:
        counter += 1
        candidate = f"{stem}-{counter}{suffix}"
    return candidate


def recipe_to_dict(recipe: Recipe) -> dict[str, Any]:
    return {
        "title": recipe.title,
        "source_url": recipe.source_url,
        "author": recipe.author,
        "description": recipe.description,
        "yields": recipe.yields,
        "total_time": recipe.total_time,
        "prep_time": recipe.prep_time,
        "cook_time": recipe.cook_time,
        "image": recipe.image,
        "ingredients": recipe.ingredients,
        "instructions": recipe.instructions,
        "site_name": recipe.site_name,
    }


def _normalize_ingredients(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_coerce_text(item) for item in value if _coerce_text(item)]


def _normalize_instructions(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_coerce_text(item) for item in value if _coerce_text(item)]
    if isinstance(value, str):
        raw_steps = [step.strip() for step in value.split("\n") if step.strip()]
        return [step for step in raw_steps if step]
    return []


def _looks_like_recipe_link(path: str, text: str) -> bool:
    path_lower = path.lower()
    if any(part in path_lower for part in ("/recipe/", "/recipes/")):
        return True
    return any(
        keyword in f"{path_lower} {text}"
        for keyword in ("pasta", "recipe", "risotto", "soup", "cake", "bread")
    )


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    normalized_path = parsed.path.rstrip("/") or "/"
    return parsed._replace(query="", fragment="", path=normalized_path).geturl()


def _deduplicate_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
