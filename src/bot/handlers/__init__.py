from aiogram import Router

from src.bot.handlers import announce, callbacks, commands, game_flow, menu, onboarding, stream_end


def setup_routers() -> Router:
    root = Router()
    root.include_router(commands.router)
    root.include_router(onboarding.router)
    root.include_router(menu.router)
    root.include_router(announce.router)
    root.include_router(game_flow.router)
    root.include_router(callbacks.router)
    root.include_router(stream_end.router)
    return root
