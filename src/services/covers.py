"""Обложки игр без обязательной регистрации — Steam Store Search API."""

from __future__ import annotations

import random

import httpx

from src.config import get_settings

STEAM_SEARCH = "https://store.steampowered.com/api/storesearch/"


async def fetch_cover_url(game_name: str) -> str | None:
    """Возвращает URL обложки или None."""
    url = await _steam_cover(game_name)
    if url:
        return url
    if get_settings().rawg_api_key:
        return await _rawg_cover(game_name)
    return None


async def _steam_cover(game_name: str) -> str | None:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(STEAM_SEARCH, params={"term": game_name, "cc": "us", "l": "english"})
        if r.status_code != 200:
            return None
        items = r.json().get("items", [])
        if not items:
            return None
        # Берём лучшее совпадение или случайное из топ-3
        pick = random.choice(items[: min(3, len(items))])
        return pick.get("tiny_image") or pick.get("header_image")


async def _rawg_cover(game_name: str) -> str | None:
    key = get_settings().rawg_api_key
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://api.rawg.io/api/games",
            params={"key": key, "search": game_name, "page_size": 3},
        )
        if r.status_code != 200:
            return None
        results = r.json().get("results", [])
        if not results:
            return None
        pick = random.choice(results)
        return pick.get("background_image")
