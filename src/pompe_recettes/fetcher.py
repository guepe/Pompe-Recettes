from __future__ import annotations

import requests


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


SESSION = requests.Session()
SESSION.headers.update(DEFAULT_HEADERS)


def fetch_html(url: str, timeout: int = 10) -> str:
    response = SESSION.get(url, timeout=timeout)
    response.raise_for_status()
    if not response.encoding:
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text
