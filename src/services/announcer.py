"""Посты в Telegram: старт, завершение, таймеры удаления."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AnnounceTarget, PlatformConnection, StreamSession, User
from src.services.covers import fetch_cover_url
from src.services.phrases import get_phrase

logger = logging.getLogger(__name__)


def _format_duration(start: datetime, end: datetime) -> str:
    delta = end - start
    hours, rem = divmod(int(delta.total_seconds()), 3600)
    minutes = rem // 60
    if hours:
        return f"{hours}ч {minutes}м"
    return f"{minutes}м"


async def post_stream_start(bot: Bot, session: AsyncSession, user: User, stream: StreamSession) -> None:
    target = await _get_target(session, user.id)
    if not target:
        return
    game = stream.game_name or "Стрим"
    phrase = get_phrase(game)
    started = stream.started_at.astimezone().strftime("%H:%M")
    text = (
        f"🔴 <b>В эфире: {game}</b>\n\n"
        f"{phrase}\n\n"
        f"🕐 Начало: {started}\n"
        f"⏱ Идёт: 0м"
    )
    keyboard = await _stream_links_keyboard(session, user.id)
    cover = await fetch_cover_url(game)
    if cover:
        msg = await bot.send_photo(
            target.chat_id,
            photo=cover,
            caption=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    else:
        msg = await bot.send_message(
            target.chat_id,
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    stream.live_message_id = msg.message_id
    await session.commit()


async def post_stream_end(bot: Bot, session: AsyncSession, user: User, stream: StreamSession) -> None:
    """Запрашивает у стримера опциональные поля и публикует пост о завершении."""
    game = stream.game_name or "Стрим"
    ended = stream.ended_at or datetime.now(UTC)
    duration = _format_duration(stream.started_at, ended)
    peak = stream.peak_viewers or 0

    lines = [
        "🔴 <b>Стрим завершён</b>",
        "",
        f"🎮 {game}",
        f"⏱ Длился: {duration}",
        f"👀 Пик зрителей: {peak}",
    ]
    if stream.end_summary:
        lines.extend(["", stream.end_summary])
    lines.extend(["", "Спасибо всем, кто заходил и болел в чате 🙏"])
    if stream.next_stream_hint:
        lines.extend(["", stream.next_stream_hint])

    text = "\n".join(lines)
    target = await _get_target(session, user.id)
    if not target:
        return

    # Удалить пост о старте через 10 минут — планируется снаружи
    msg = await bot.send_message(target.chat_id, text, parse_mode="HTML")
    stream.end_message_id = msg.message_id
    await session.commit()


async def ask_end_details(bot: Bot, telegram_id: int) -> None:
    await bot.send_message(
        telegram_id,
        "Стрим завершился.\n\n"
        "Хочешь добавить краткий итог вечера? Напиши текст или отправь /skip\n\n"
        "После этого спрошу про следующий эфир (или /skip).",
    )


async def _get_target(session: AsyncSession, user_id: int) -> AnnounceTarget | None:
    r = await session.execute(select(AnnounceTarget).where(AnnounceTarget.user_id == user_id))
    return r.scalar_one_or_none()


async def _stream_links_keyboard(session: AsyncSession, user_id: int) -> InlineKeyboardMarkup | None:
    r = await session.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user_id,
            PlatformConnection.enabled.is_(True),
        )
    )
    buttons: list[list[InlineKeyboardButton]] = []
    for conn in r.scalars():
        if conn.external_channel_name:
            name = conn.platform.capitalize()
            url = _channel_url(conn.platform, conn.external_channel_name)
            if url:
                buttons.append([InlineKeyboardButton(text=name, url=url)])
    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None


def _channel_url(platform: str, channel_name: str) -> str | None:
    mapping = {
        "twitch": f"https://twitch.tv/{channel_name}",
        "kick": f"https://kick.com/{channel_name}",
        "youtube": f"https://youtube.com/channel/{channel_name}",
        "vk": f"https://live.vkvideo.ru/{channel_name}",
        "trovo": f"https://trovo.live/s/{channel_name}",
    }
    return mapping.get(platform)


async def delete_message_safe(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.debug("delete_message %s:%s — %s", chat_id, message_id, e)
