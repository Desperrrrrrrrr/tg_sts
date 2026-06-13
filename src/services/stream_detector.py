from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Platform, PlatformConnection, StreamSession, User
from src.platforms.registry import get_adapter
from src.services.platform_creds import get_credentials
from src.services.token_manager import get_access_token

logger = logging.getLogger(__name__)


async def poll_user_streams(session: AsyncSession, user: User) -> tuple[bool, bool]:
    result = await session.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user.id,
            PlatformConnection.enabled.is_(True),
        )
    )
    any_live = False
    total_viewers = 0
    live_title: str | None = None
    live_game: str | None = None

    for conn in result.scalars():
        creds = await get_credentials(session, conn)
        token = await get_access_token(session, conn)
        if not creds or not token or not conn.external_channel_id:
            continue
        adapter = get_adapter(Platform(conn.platform))
        try:
            info = await adapter.get_stream_info(token, conn.external_channel_id, creds)
            if info.is_live:
                any_live = True
                total_viewers += info.viewer_count
                live_title = live_title or info.title
                live_game = live_game or info.category_name
        except Exception as e:
            logger.warning("poll %s: %s", conn.platform, e)

    open_session = await _get_open_session(session, user.id)
    was_live = open_session is not None

    if any_live and not was_live:
        session.add(
            StreamSession(
                user_id=user.id,
                game_name=live_game,
                title=live_title,
                started_at=datetime.now(UTC),
                peak_viewers=total_viewers,
            )
        )
        await session.commit()
        return True, False

    if not any_live and was_live and open_session:
        open_session.ended_at = datetime.now(UTC)
        if total_viewers > (open_session.peak_viewers or 0):
            open_session.peak_viewers = total_viewers
        await session.commit()
        return False, True

    if any_live and was_live and open_session and total_viewers > (open_session.peak_viewers or 0):
        open_session.peak_viewers = total_viewers
        await session.commit()

    return False, False


async def _get_open_session(session: AsyncSession, user_id: int) -> StreamSession | None:
    r = await session.execute(
        select(StreamSession).where(StreamSession.user_id == user_id, StreamSession.ended_at.is_(None))
    )
    return r.scalar_one_or_none()
