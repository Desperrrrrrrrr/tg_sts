"""Обновление стрима на одной или всех площадках."""

from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import PLATFORM_LABELS, Platform, PlatformConnection
from src.platforms.registry import get_adapter
from src.services.platform_creds import get_credentials
from src.services.titles import PreparedTitle, prepare_title
from src.services.token_manager import get_access_token
from src.services.vk_session import get_vk_web_access_token

# VK: slug канала в external_channel_name; OAuth-токен достаточен для API.
_PLATFORMS_WITHOUT_CHANNEL_ID = {Platform.VK}


def _channel_id_for(conn: PlatformConnection, plat: Platform) -> str:
    if plat == Platform.VK:
        return conn.external_channel_name or conn.external_channel_id or ""
    return conn.external_channel_id or ""


def _format_api_error(label: str, exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        body = exc.response.text[:300]
        try:
            payload = exc.response.json()
            msg = payload.get("message") or payload.get("error_description") or payload.get("error")
            if msg:
                return f"{label}: {exc.response.status_code} — {msg}"
        except Exception:
            pass
        if body:
            return f"{label}: {exc.response.status_code} — {body}"
    return f"{label}: {exc}"


async def update_on_platforms(
    session: AsyncSession,
    user_id: int,
    *,
    platform_filter: Platform | None = None,
    title: str | None = None,
    category_id: str | None = None,
) -> list[str]:
    errors: list[str] = []
    r = await session.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user_id,
            PlatformConnection.enabled.is_(True),
        )
    )
    for conn in r.scalars():
        if platform_filter and conn.platform != platform_filter.value:
            continue
        plat = Platform(conn.platform)
        label = PLATFORM_LABELS.get(plat, conn.platform)
        creds = await get_credentials(session, conn)
        if not creds:
            errors.append(f"{label}: нет ключей приложения")
            continue
        token = await get_access_token(session, conn)
        if not token:
            errors.append(f"{label}: не авторизован (нет токена)")
            continue
        if plat not in _PLATFORMS_WITHOUT_CHANNEL_ID and not conn.external_channel_id:
            errors.append(f"{label}: не авторизован (нет ID канала)")
            continue
        adapter = get_adapter(plat)
        channel_id = _channel_id_for(conn, plat)
        send_title = title
        if title is not None:
            prepared: PreparedTitle = prepare_title(title, plat)
            send_title = prepared.text
        try:
            extra: dict = {}
            if plat == Platform.VK:
                web_token = await get_vk_web_access_token(session, conn)
                if web_token:
                    extra["web_access_token"] = web_token
            await adapter.update_stream(
                token,
                channel_id,
                creds,
                title=send_title,
                category_id=category_id,
                **extra,
            )
        except Exception as e:
            err = _format_api_error(label, e)
            if plat == Platform.VK and ("session" in str(e).lower() or "401" in err):
                errors.append(
                    f"{label}: для смены игры нужен session-токен из браузера "
                    "(⚙️ → VK → отправь «🔑 Session» и вставь auth из localStorage)."
                )
            else:
                errors.append(err)
    return errors


async def verify_platform_category(
    session: AsyncSession,
    user_id: int,
    platform: Platform,
    expected_name: str,
) -> str | None:
    r = await session.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user_id,
            PlatformConnection.platform == platform.value,
            PlatformConnection.enabled.is_(True),
        )
    )
    conn = r.scalar_one_or_none()
    if not conn:
        return None
    creds = await get_credentials(session, conn)
    token = await get_access_token(session, conn)
    if not creds or not token:
        return None
    if platform not in _PLATFORMS_WITHOUT_CHANNEL_ID and not conn.external_channel_id:
        return None
    adapter = get_adapter(platform)
    channel_id = _channel_id_for(conn, platform)
    try:
        if platform == Platform.TWITCH and hasattr(adapter, "get_channel_category"):
            name = await adapter.get_channel_category(token, channel_id, creds)
            if name:
                mark = "✅" if _names_match(expected_name, name) else "⚠️"
                return f"{mark} категория: «{name}»"
        if platform == Platform.TWITCH and hasattr(adapter, "get_channel_title"):
            pass
        info = await adapter.get_stream_info(token, channel_id, creds)
        if info.category_name:
            mark = "✅" if _names_match(expected_name, info.category_name) else "⚠️"
            return f"{mark} категория: «{info.category_name}»"
    except Exception:
        pass
    return None


async def verify_platform_title(
    session: AsyncSession,
    user_id: int,
    platform: Platform,
    expected_title: str,
) -> str | None:
    r = await session.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user_id,
            PlatformConnection.platform == platform.value,
            PlatformConnection.enabled.is_(True),
        )
    )
    conn = r.scalar_one_or_none()
    if not conn:
        return None
    creds = await get_credentials(session, conn)
    token = await get_access_token(session, conn)
    if not creds or not token:
        return None
    if platform not in _PLATFORMS_WITHOUT_CHANNEL_ID and not conn.external_channel_id:
        return None
    adapter = get_adapter(platform)
    channel_id = _channel_id_for(conn, platform)
    prepared = prepare_title(expected_title, platform)
    try:
        current: str | None = None
        if hasattr(adapter, "get_channel_title"):
            current = await adapter.get_channel_title(token, channel_id, creds)
        if not current:
            info = await adapter.get_stream_info(token, channel_id, creds)
            current = info.title
        if current:
            mark = "✅" if _names_match(prepared.text, current) else "⚠️"
            return f"{mark} название: «{current}»"
    except Exception:
        pass
    return None


def _names_match(a: str, b: str) -> bool:
    al, bl = a.lower().strip(), b.lower().strip()
    return al == bl or al in bl or bl in al
