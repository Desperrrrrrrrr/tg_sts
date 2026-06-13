from aiogram import Bot

_runtime_bot: Bot | None = None


def set_runtime_bot(bot: Bot) -> None:
    global _runtime_bot
    _runtime_bot = bot


def get_runtime_bot() -> Bot | None:
    return _runtime_bot
