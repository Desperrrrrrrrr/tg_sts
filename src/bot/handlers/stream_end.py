"""Диалог со стримером после завершения стрима."""

from __future__ import annotations

from dataclasses import dataclass

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy import select

from src.bot.runtime import get_runtime_bot
from src.db.database import get_session_factory
from src.db.models import StreamSession, User
from src.services.announcer import post_stream_end

router = Router()


@dataclass
class EndPrompt:
    session_id: int
    stage: str  # summary | next


_pending: dict[int, EndPrompt] = {}


def start_end_prompt(telegram_id: int, session_id: int) -> None:
    _pending[telegram_id] = EndPrompt(session_id=session_id, stage="summary")


def _in_end_prompt(message: Message) -> bool:
    return message.from_user is not None and message.from_user.id in _pending


@router.message(F.text, F.func(_in_end_prompt))
async def end_stream_dialog(message: Message) -> None:
    prompt = _pending[message.from_user.id]
    if message.text.startswith("/"):
        if message.text != "/skip":
            return

    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(StreamSession).where(StreamSession.id == prompt.session_id))
        stream = r.scalar_one_or_none()
        if not stream:
            _pending.pop(message.from_user.id, None)
            return

        if prompt.stage == "summary":
            stream.end_summary = None if message.text == "/skip" else message.text.strip()
            await session.commit()
            prompt.stage = "next"
            await message.answer("Когда следующий эфир? Напиши или /skip")
            return

        if prompt.stage == "next":
            hint = None if message.text == "/skip" else message.text.strip()
            stream.next_stream_hint = f"Следующий эфир — {hint}" if hint else None
            await session.commit()
            _pending.pop(message.from_user.id, None)
            r2 = await session.execute(select(User).where(User.id == stream.user_id))
            user = r2.scalar_one()
            bot = get_runtime_bot()
            if bot:
                await post_stream_end(bot, session, user, stream)
            await message.answer("Пост о завершении опубликован.")
