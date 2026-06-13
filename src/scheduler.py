"""Фоновые задачи: polling стримов, удаление постов."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from src.bot.handlers.stream_end import start_end_prompt
from src.db.database import get_session_factory
from src.db.models import AnnounceTarget, StreamSession, User
from src.services.announcer import ask_end_details, delete_message_safe, post_stream_start
from src.services.stream_detector import poll_user_streams

logger = logging.getLogger(__name__)

_scheduled_deletes: list[tuple[int, int, datetime]] = []


def schedule_delete(chat_id: int, message_id: int, delay_minutes: int) -> None:
    _scheduled_deletes.append((chat_id, message_id, datetime.now(UTC) + timedelta(minutes=delay_minutes)))


async def _poll_all_streams(bot) -> None:
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User))
        for user in r.scalars():
            went_live, went_offline = await poll_user_streams(session, user)
            if went_live:
                r2 = await session.execute(
                    select(StreamSession).where(
                        StreamSession.user_id == user.id,
                        StreamSession.ended_at.is_(None),
                    )
                )
                stream = r2.scalar_one_or_none()
                if stream:
                    await post_stream_start(bot, session, user, stream)
            if went_offline:
                r2 = await session.execute(
                    select(StreamSession)
                    .where(
                        StreamSession.user_id == user.id,
                        StreamSession.ended_at.is_not(None),
                        StreamSession.end_message_id.is_(None),
                    )
                    .order_by(StreamSession.ended_at.desc())
                )
                stream = r2.scalars().first()
                if stream:
                    tr = await session.execute(
                        select(AnnounceTarget).where(AnnounceTarget.user_id == user.id)
                    )
                    target = tr.scalar_one_or_none()
                    if stream.live_message_id and target:
                        schedule_delete(target.chat_id, stream.live_message_id, 10)
                    start_end_prompt(user.telegram_id, stream.id)
                    await ask_end_details(bot, user.telegram_id)


async def _process_deletes(bot) -> None:
    now = datetime.now(UTC)
    remaining = []
    for chat_id, msg_id, at in _scheduled_deletes:
        if now >= at:
            await delete_message_safe(bot, chat_id, msg_id)
        else:
            remaining.append((chat_id, msg_id, at))
    _scheduled_deletes.clear()
    _scheduled_deletes.extend(remaining)

    # Удаление поста о завершении через 1 час
    factory = get_session_factory()
    async with factory() as session:
        cutoff = now - timedelta(hours=1)
        r = await session.execute(
            select(StreamSession).where(
                StreamSession.end_message_id.is_not(None),
                StreamSession.ended_at.is_not(None),
                StreamSession.ended_at <= cutoff,
            )
        )
        for stream in r.scalars():
            tr = await session.execute(
                select(AnnounceTarget).where(AnnounceTarget.user_id == stream.user_id)
            )
            target = tr.scalar_one_or_none()
            if target and stream.end_message_id:
                await delete_message_safe(bot, target.chat_id, stream.end_message_id)
                stream.end_message_id = None
        await session.commit()


def start_scheduler(bot) -> AsyncIOScheduler:
    sched = AsyncIOScheduler()
    sched.add_job(_poll_all_streams, "interval", minutes=2, args=[bot], id="poll_streams")
    sched.add_job(_process_deletes, "interval", seconds=30, args=[bot], id="deletes")
    sched.start()
    return sched
