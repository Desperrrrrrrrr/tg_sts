"""Точка входа: Telegram-бот + OAuth-сервер + планировщик."""

from __future__ import annotations

import asyncio
import logging

import uvicorn

from src.api.oauth import create_oauth_app
from src.bot.app import create_bot
from src.bot.dispatcher import create_dispatcher
from src.bot.runtime import set_runtime_bot
from src.config import get_settings
from src.db.database import init_db
from src.scheduler import start_scheduler
from src.services.public_url import public_base_url_configured

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def run_bot(dp, bot) -> None:
    await dp.start_polling(bot)


async def main() -> None:
    settings = get_settings()
    await init_db()

    bot = create_bot()
    set_runtime_bot(bot)
    dp = create_dispatcher()
    start_scheduler(bot)

    oauth_app = create_oauth_app()
    config = uvicorn.Config(oauth_app, host=settings.host, port=settings.port, log_level="info")
    server = uvicorn.Server(config)

    logger.info("StreamSync: bot + OAuth on %s:%s", settings.host, settings.port)
    logger.info("PUBLIC_BASE_URL=%s", settings.public_base_url)
    if not public_base_url_configured():
        logger.warning(
            "PUBLIC_BASE_URL looks like a placeholder — OAuth will fail until you set a real URL in .env"
        )
    await asyncio.gather(run_bot(dp, bot), server.serve())


if __name__ == "__main__":
    asyncio.run(main())
