from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_PROJECT_CONFIG_PATH = Path("config/project.toml")


@dataclass(slots=True)
class RunConfig:
    url: str = ""
    max_pages: int = 12
    max_recipes: int = 3
    crawl_workers: int = 4
    request_timeout: int = 10
    translate_mode: str = "auto"
    translate_fr: bool = True
    push_notion: bool = True
    output: str = ""
    output_dir: str = ""
    json: bool = False


@dataclass(slots=True)
class ProjectConfig:
    run: RunConfig = field(default_factory=RunConfig)
    raw: dict | None = None


def load_project_config(path: str | Path = DEFAULT_PROJECT_CONFIG_PATH) -> ProjectConfig:
    config_path = Path(path)
    if not config_path.exists():
        return ProjectConfig()

    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    run_raw = raw.get("run", {})
    translate_mode_raw = run_raw.get("translate_mode")
    if translate_mode_raw is None:
        translate_mode = "auto" if bool(run_raw.get("translate_fr", True)) else "off"
    else:
        translate_mode = str(translate_mode_raw).strip().lower() or "auto"

    run = RunConfig(
        url=run_raw.get("url", ""),
        max_pages=int(run_raw.get("max_pages", 12)),
        max_recipes=int(run_raw.get("max_recipes", 3)),
        crawl_workers=int(run_raw.get("crawl_workers", 4)),
        request_timeout=int(run_raw.get("request_timeout", 10)),
        translate_mode=translate_mode,
        translate_fr=bool(run_raw.get("translate_fr", True)),
        push_notion=bool(run_raw.get("push_notion", True)),
        output=run_raw.get("output", ""),
        output_dir=run_raw.get("output_dir", ""),
        json=bool(run_raw.get("json", False)),
    )
    return ProjectConfig(run=run, raw=raw)
