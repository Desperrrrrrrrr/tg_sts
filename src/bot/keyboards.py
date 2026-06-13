from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.db.models import PLATFORM_LABELS, Platform
from src.platforms.base import CategoryResult


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📡 Площадки", callback_data="menu:platforms")],
            [InlineKeyboardButton(text="📊 Статус", callback_data="menu:status")],
            [InlineKeyboardButton(text="🎮 Сменить игру", callback_data="menu:game")],
            [InlineKeyboardButton(text="✏️ Сменить название", callback_data="menu:title")],
            [InlineKeyboardButton(text="📢 Канал анонсов", callback_data="menu:announce")],
        ]
    )


def platforms_menu(connections: dict[str, bool]) -> InlineKeyboardMarkup:
    rows = []
    for p in Platform:
        label = PLATFORM_LABELS[p]
        enabled = connections.get(p.value, False)
        icon = "✅" if enabled else "➕"
        rows.append([
            InlineKeyboardButton(text=f"{icon} {label}", callback_data=f"plat:{p.value}"),
        ])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def platform_actions(platform: Platform, connected: bool, enabled: bool) -> InlineKeyboardMarkup:
    rows = []
    if not connected:
        rows.append([InlineKeyboardButton(text="🔗 Подключить", callback_data=f"connect:{platform.value}")])
    else:
        toggle = "⏸ Отключить" if enabled else "▶️ Включить"
        rows.append([InlineKeyboardButton(text=toggle, callback_data=f"toggle:{platform.value}")])
        rows.append([InlineKeyboardButton(text="🔄 Переподключить", callback_data=f"connect:{platform.value}")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="menu:platforms")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def category_confirm(platform: str, category_id: str, category_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"catok:{platform}:{category_id}"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"catno:{platform}"),
            ],
            [
                InlineKeyboardButton(text="📂 Other", callback_data=f"catother:{platform}"),
                InlineKeyboardButton(text="🔎 Уточнить", callback_data=f"catrefine:{platform}"),
            ],
        ]
    )


def _choice_pairs(choices: list[tuple[str, str]] | list[CategoryResult]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for item in choices:
        if isinstance(item, CategoryResult):
            pairs.append((item.id, item.name))
        else:
            pairs.append(item)
    return pairs


def title_skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data="titleskip")],
        ]
    )


def category_choices(
    platform: str,
    choices: list[tuple[str, str]] | list[CategoryResult],
    *,
    show_other: bool = True,
    show_refine: bool = True,
    columns: int = 2,
) -> InlineKeyboardMarkup:
    pairs = _choice_pairs(choices)
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(pairs), columns):
        row = [
            InlineKeyboardButton(text=name, callback_data=f"catpick:{platform}:{cid}")
            for cid, name in pairs[i : i + columns]
        ]
        rows.append(row)
    extra: list[InlineKeyboardButton] = []
    if show_refine:
        extra.append(InlineKeyboardButton(text="🔎 Уточнить", callback_data=f"catrefine:{platform}"))
    if show_other:
        extra.append(InlineKeyboardButton(text="📂 Other", callback_data=f"catother:{platform}"))
    if extra:
        rows.append(extra)
    return InlineKeyboardMarkup(inline_keyboard=rows)
