"""Подготовка названия стрима под лимиты площадок."""

from __future__ import annotations

from dataclasses import dataclass

from src.db.models import Platform

# Twitch: официально 140 символов (счётчик на сайте — символы, не байты).
TITLE_LIMITS: dict[Platform, int] = {
    Platform.TWITCH: 140,
    Platform.KICK: 200,
    Platform.VK: 200,
    Platform.YOUTUBE: 100,
    Platform.TROVO: 200,
}


@dataclass
class PreparedTitle:
    text: str
    truncated: bool
    original_len: int
    note: str | None = None


def prepare_title(title: str, platform: Platform) -> PreparedTitle:
    raw = title.strip().replace("\r\n", " ").replace("\n", " ")
    while "  " in raw:
        raw = raw.replace("  ", " ")
    original_len = len(raw)
    limit = TITLE_LIMITS.get(platform, 140)
    truncated = False
    note_parts: list[str] = []

    if len(raw) > limit:
        raw = raw[:limit].rstrip()
        truncated = True
        note_parts.append(f"обрезано до {limit} символов")

    note = "; ".join(note_parts) if note_parts else None
    return PreparedTitle(text=raw, truncated=truncated, original_len=original_len, note=note)


def format_title_hint(platform: Platform) -> str:
    limit = TITLE_LIMITS.get(platform, 140)
    return f"до {limit} символов"
