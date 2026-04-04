from __future__ import annotations

import re

from pompe_recettes.models import Recipe


def render_markdown(recipe: Recipe) -> str:
    lines: list[str] = [f"# {recipe.title}", ""]

    if recipe.description:
        lines.extend([recipe.description.strip(), ""])

    metadata = _metadata_lines(recipe)
    if metadata:
        lines.extend(["## Propriétés", ""])
        lines.extend(metadata)
        lines.append("")

    if recipe.ingredients:
        lines.extend(["## Ingrédients", ""])
        lines.extend(f"- {item}" for item in recipe.ingredients if item.strip())
        lines.append("")

    if recipe.instructions:
        lines.extend(["## Etapes", ""])
        lines.extend(
            f"{index}. {step}"
            for index, step in enumerate(recipe.instructions, start=1)
            if step.strip()
        )
        lines.append("")

    lines.extend(["## Source", "", recipe.source_url])

    return "\n".join(lines).strip() + "\n"


def recipe_filename(recipe: Recipe) -> str:
    slug = slugify(recipe.title) or "recette"
    return f"{slug}.md"


def _metadata_lines(recipe: Recipe) -> list[str]:
    values: list[tuple[str, str | None]] = [
        ("Site", recipe.site_name),
        ("Auteur", recipe.author),
        ("Portions", recipe.yields),
        ("Temps total", _format_minutes(recipe.total_time)),
        ("Preparation", _format_minutes(recipe.prep_time)),
        ("Cuisson", _format_minutes(recipe.cook_time)),
        ("Image", recipe.image),
    ]
    return [f"- **{label}** : {value}" for label, value in values if value]


def _format_minutes(value: int | None) -> str | None:
    if value is None:
        return None
    if value < 60:
        return f"{value} min"
    hours, minutes = divmod(value, 60)
    if minutes == 0:
        return f"{hours} h"
    return f"{hours} h {minutes} min"


def slugify(value: str) -> str:
    lowered = value.lower().strip()
    lowered = re.sub(r"[^\w\s-]", "", lowered)
    lowered = re.sub(r"[-\s]+", "-", lowered)
    return lowered.strip("-")
