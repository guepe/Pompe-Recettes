# Supported Sites

Pompe Recettes relies on two layers:

- the upstream [`recipe-scrapers`](https://github.com/hhursev/recipe-scrapers) ecosystem
- local site-specific overrides implemented in this project

## Upstream Supported Sites

The main supported-sites reference comes from the official `recipe-scrapers` documentation:

- Official list: https://docs.recipe-scrapers.com/getting-started/supported-sites/#exec-2--supported-sites-list

That list contains hundreds of supported websites and should be treated as the primary source of truth for built-in extraction support.

Examples of sites that are relevant to this project and already supported upstream include:

- `hellofresh.be`
- `hellofresh.fr`
- `hellofresh.com`
- `anitalianinmykitchen.com`
- `jow.fr`
- `quitoque.fr`
- `marmiton.org`
- `blueapron.com`

## Local Overrides In This Project

Some websites are not supported by `recipe-scrapers` or need project-specific extraction logic.

Those sites are handled in [`src/pompe_recettes/site_overrides.py`](./src/pompe_recettes/site_overrides.py).

Currently handled locally:

- `colruyt.be`

## How Support Works

When a URL is processed, Pompe Recettes tries:

1. a local site override if one exists
2. the default `recipe-scrapers` extractor
3. internal crawling when the initial page is not a recipe page

This lets the project stay compatible with the upstream ecosystem while still covering websites that need custom handling.
