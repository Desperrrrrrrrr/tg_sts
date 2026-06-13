"""Цепляющие фразы для анонсов — по игре или жанру."""

from __future__ import annotations

import random

# Точные совпадения (нижний регистр)
EXACT: dict[str, list[str]] = {
    "dark souls": [
        "Ну что, какой сегодня будет самый душный босс? Сейчас и узнаем...",
        "Костёр зажжён — значит, боль начинается.",
    ],
    "dark souls iii": [
        "Pontiff ждёт. Или это мы его ждём?",
        "Третий раз — не считается, если умер на боссе.",
    ],
    "elden ring": [
        "Открываем карту — и сразу в боль. Поехали.",
        "«Ещё один босс» — famous last words.",
    ],
    "counter-strike 2": [
        "Разминка пальцев. Сегодня без оправданий.",
        "Эконом-раунд? Нет, только хайлайты.",
    ],
    "dota 2": [
        "Один фид — и весь чат в деле. Заходите.",
        "Сегодня лес не виноват. Наверное.",
    ],
    "just chatting": [
        "Заходите — тут будет интереснее, чем в ленте.",
        "Кофе есть, мысли тоже. Обсудим?",
    ],
}

GENERIC = [
    "Погнали — сегодня будет жарко.",
    "Заходи, не стесняйся. Мы тут своих ждём.",
    "Стрим пошёл. Опоздавшие — в чат с «+».",
    "Новая сессия, новые истории. Включайся.",
]


def get_phrase(game_name: str) -> str:
    key = game_name.lower().strip()
    if key in EXACT:
        return random.choice(EXACT[key])
    for name, phrases in EXACT.items():
        if name in key or key in name:
            return random.choice(phrases)
    return random.choice(GENERIC)
