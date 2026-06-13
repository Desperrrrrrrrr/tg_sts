from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import get_settings


def create_bot() -> Bot:
    return Bot(
        token=get_settings().telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
