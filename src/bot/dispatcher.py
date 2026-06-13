from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from src.bot.handlers import setup_routers


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(setup_routers())
    return dp
