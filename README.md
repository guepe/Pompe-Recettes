# Pompe Recettes

Turn recipe URLs into clean, Notion-friendly content.

`Pompe Recettes` is a Python project that extracts recipes from supported cooking websites, normalizes them, optionally translates them to French, converts common units to a more European format, and can push the result directly into a Notion database.

It is built on top of [`recipe-scrapers`](https://github.com/hhursev/recipe-scrapers), with a few extra layers:

- site crawling when the starting URL is not a recipe page
- Markdown output tailored for Notion
- optional French localization
- direct Notion database export
- site-specific overrides for unsupported websites such as `colruyt.be`

## Why This Project

Recipe sites are all slightly different.

Some pages expose structured recipe metadata nicely. Some do not. Some category pages are just entry points. And once the data is extracted, it still needs to be cleaned up before it becomes useful in a personal knowledge base.

This project focuses on that full workflow:

1. start from a recipe URL or category URL
2. find valid recipe pages if needed
3. extract the recipe
4. normalize content
5. optionally translate to French
6. export to Markdown and/or push to Notion

## Features

- Extract recipes from websites supported by `recipe-scrapers`
- Crawl internal links when the initial page is not itself a recipe
- Export clean Markdown with Notion-friendly sections
- Output one Markdown file or one file per recipe
- Push recipes directly to a Notion database
- Use a global project config instead of repeating CLI arguments
- Add site-specific extraction fallbacks for unsupported websites
- Support `colruyt.be` through a custom override layer

## Project Layout

- Main config: [`config/project.toml`](./config/project.toml)
- Config template: [`config/project.toml.sample`](./config/project.toml.sample)
- CLI entrypoint: [`src/pompe_recettes/cli.py`](./src/pompe_recettes/cli.py)
- Notion export helpers: [`src/pompe_recettes/notion_export`](./src/pompe_recettes/notion_export)
- Site-specific overrides: [`src/pompe_recettes/site_overrides.py`](./src/pompe_recettes/site_overrides.py)
- Supported sites reference: [`SUPPORTED_SITES.md`](./SUPPORTED_SITES.md)

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Quick Start

### 1. Configure the project

Copy the sample config if needed:

```bash
cp config/project.toml.sample config/project.toml
```

Then edit [`config/project.toml`](./config/project.toml).

The project supports a global configuration file so you can run it without passing the same flags every time.

### 2. Set your Notion token

If you want to push recipes to Notion, define the token referenced by `token_env`:

```bash
export NOTION_TOKEN="secret_xxx"
```

### 3. Run the CLI

With a direct URL:

```bash
pompe-recettes "https://www.hellofresh.fr/recipes/..."
```

Or using the URL configured in `config/project.toml`:

```bash
pompe-recettes
```

## Global Configuration

The recommended entrypoint is [`config/project.toml`](./config/project.toml).

It contains two sections:

- `[run]` for runtime behavior
- `[notion]` for Notion export settings

Example:

```toml
[run]
url = "https://anitalianinmykitchen.com/category/ingredient/pasta-2/"
max_pages = 12
max_recipes = 3
translate_fr = true
push_notion = true
output = ""
output_dir = ""
json = false

[notion]
token_env = "NOTION_TOKEN"
database_url = "https://www.notion.so/your-workspace/your-database-id?v=your-view-id"
notion_version = "2026-03-11"
include_markdown_block = false
use_recipe_image_as_cover = true

[notion.properties]
title = "Name"
source_url = "Source"
prep_time = "Prep Time"
cook_time = "Cook Time"
```

CLI arguments still work and override the config when provided.

## CLI Usage

Basic:

```bash
pompe-recettes "https://anitalianinmykitchen.com/category/ingredient/pasta-2/"
```

Use another config file:

```bash
pompe-recettes --config config/project.toml
```

Write Markdown to a single file:

```bash
pompe-recettes "https://www.hellofresh.fr/recipes/..." --output recipe.md
```

Write one file per recipe:

```bash
pompe-recettes "https://anitalianinmykitchen.com/category/ingredient/pasta-2/" --output-dir recipes
```

Disable Notion push temporarily:

```bash
pompe-recettes "https://anitalianinmykitchen.com/category/ingredient/pasta-2/" --no-push-notion
```

Keep the original source language:

```bash
pompe-recettes "https://anitalianinmykitchen.com/category/ingredient/pasta-2/" --no-translate-fr
```

Return raw JSON:

```bash
pompe-recettes "https://www.hellofresh.fr/recipes/..." --json
```

## Markdown Output

Generated Markdown is designed to paste well into Notion pages.

It includes:

- recipe title
- properties section
- ingredient bullet list
- numbered steps
- source URL

## Notion Integration

The project includes a small Notion export layer that can create pages in a Notion database and append recipe content as blocks.

Supported export content:

- title
- description
- source URL
- author
- yields
- times
- recipe cover image
- site name
- ingredient bullet list
- recipe steps

The recipe source URL is also used as the duplicate-prevention key during Notion export when the target database has a compatible `url` or `rich_text` property mapped to `source_url`.

### Notion Requirements

- your integration must have access to the target database
- the database must be shared with the integration
- the token must be available through the environment variable defined by `token_env`

The config accepts:

- `data_source_id`
- `database_id`
- `database_url`

Using `database_url` is usually the easiest option.

When `use_recipe_image_as_cover = true`, the recipe image is sent as the page cover in Notion instead of being pushed into a database property. The image URL must be public and available over HTTPS.

## Python Usage

You can also use the project programmatically.

### Collect recipes

```python
from pompe_recettes.cli import collect_recipes

recipes = collect_recipes(
    "https://anitalianinmykitchen.com/category/ingredient/pasta-2/",
    max_pages=6,
    max_recipes=2,
)
```

### Export to Notion

```python
from pompe_recettes.cli import collect_recipes
from pompe_recettes.notion_export import build_exporter_from_config

recipes = collect_recipes(
    "https://anitalianinmykitchen.com/category/ingredient/pasta-2/",
    max_pages=6,
    max_recipes=1,
)

config, exporter = build_exporter_from_config("config/project.toml")
parent_type, parent_id, schema_properties = exporter.resolve_parent(
    data_source_id=config.data_source_id,
    database_id=config.database_id,
)

page = exporter.export_recipe(
    parent_id=parent_id,
    parent_type=parent_type,
    schema_properties=schema_properties,
    recipe=recipes[0],
    include_markdown_block=config.include_markdown_block,
)

print(page["url"])
```

## Site Overrides

When `recipe-scrapers` does not support a website, this project can provide a local override instead of failing immediately.

That is currently the case for:

- `colruyt.be`

The Colruyt implementation uses the structured `Recipe` JSON-LD present in the page, which makes it more robust than scraping fragile visual selectors.

For a broader support overview, see [`SUPPORTED_SITES.md`](./SUPPORTED_SITES.md), which links to the official `recipe-scrapers` supported-sites list and documents local overrides handled by this project.

## Current Defaults

The current CLI behavior is intentionally opinionated:

- French translation is enabled by default
- Notion push is enabled by default
- global config is read from `config/project.toml`

You can still disable those defaults with CLI flags when needed.

## Limitations

- extraction quality still depends on the source HTML
- translation is best-effort
- unit conversion is practical, not perfect scientific normalization
- some recipe sites need site-specific cleanup
- Notion mappings depend on your database schema

## Roadmap Ideas

- duplicate detection before creating Notion pages
- batch imports from URL lists
- richer nutrition and tagging support
- more site-specific overrides
- smarter ingredient normalization in French

## Credits

- [`recipe-scrapers`](https://github.com/hhursev/recipe-scrapers) for the base extraction layer
- Notion API for the database export workflow
