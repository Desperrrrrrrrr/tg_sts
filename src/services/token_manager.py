from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import PLATFORM_LABELS, Platform, PlatformConnection
from src.platforms.registry import get_adapter
from src.services.crypto import decrypt_token, encrypt_token
from src.services.platform_creds import get_credentials
from src.utils.time import as_utc, utc_now


async def get_access_token(session: AsyncSession, conn: PlatformConnection) -> str | None:
    if not conn.access_token_enc:
        return None
    token = decrypt_token(conn.access_token_enc)
    creds = await get_credentials(session, conn)
    if not creds:
        return None
    expires_at = as_utc(conn.token_expires_at)
    if expires_at and expires_at <= utc_now():
        if not conn.refresh_token_enc:
            conn.status = "error"
            conn.status_message = "Токен истёк. Переподключи площадку."
            await session.commit()
            return None
        adapter = get_adapter(Platform(conn.platform))
        try:
            refreshed = await adapter.refresh_access_token(
                decrypt_token(conn.refresh_token_enc), creds
            )
            conn.access_token_enc = encrypt_token(refreshed["access_token"])
            if refreshed.get("refresh_token"):
                conn.refresh_token_enc = encrypt_token(refreshed["refresh_token"])
            if refreshed.get("expires_in"):
                conn.token_expires_at = utc_now() + timedelta(seconds=int(refreshed["expires_in"]))
            if refreshed.get("oauth_device_id"):
                conn.oauth_device_id = refreshed["oauth_device_id"]
            conn.status = "ok"
            conn.status_message = "Подключено"
            await session.commit()
            return refreshed["access_token"]
        except Exception as e:
            conn.status = "error"
            conn.status_message = f"Не удалось обновить токен: {e}"
            await session.commit()
            return None
    return token


async def verify_platform_connection(
    session: AsyncSession, conn: PlatformConnection
) -> tuple[bool, str]:
    """Проверка после OAuth: токен в БД + живой запрос к API площадки."""
    label = PLATFORM_LABELS.get(Platform(conn.platform), conn.platform)
    if not conn.access_token_enc:
        return False, (
            f"{label}: авторизация не завершена.\n\n"
            "Открой ссылку из бота, нажми «Разрешить» в браузере. "
            "Должна открыться страница «✅ подключён»."
        )
    token = await get_access_token(session, conn)
    if not token:
        return False, conn.status_message or f"{label}: не удалось получить токен."
    creds = await get_credentials(session, conn)
    if not creds:
        return False, f"{label}: нет ключей приложения в боте."
    adapter = get_adapter(Platform(conn.platform))
    status = await adapter.check_token(token, creds)
    if not status.ok:
        conn.status = "error"
        conn.status_message = status.message
        await session.commit()
        return False, f"{label}: {status.message}"
    conn.status = "ok"
    conn.status_message = status.message
    await session.commit()
    detail = status.message
    if conn.external_channel_name:
        detail += f"\nКанал: <b>{conn.external_channel_name}</b>"
    elif conn.external_channel_id:
        detail += f"\nID: <code>{conn.external_channel_id}</code>"
    return True, detail


async def save_oauth_tokens(
    session: AsyncSession,
    conn: PlatformConnection,
    *,
    access_token: str,
    refresh_token: str | None,
    expires_in: int | None,
    channel_id: str,
    channel_name: str,
    oauth_device_id: str | None = None,
) -> None:
    conn.access_token_enc = encrypt_token(access_token)
    conn.refresh_token_enc = encrypt_token(refresh_token) if refresh_token else None
    conn.external_channel_id = channel_id
    conn.external_channel_name = channel_name
    if oauth_device_id:
        conn.oauth_device_id = oauth_device_id
    conn.connected_at = utc_now()
    conn.enabled = True
    conn.status = "ok"
    conn.status_message = "Подключено"
    if expires_in:
        conn.token_expires_at = utc_now() + timedelta(seconds=int(expires_in))
    await session.commit()


async def disconnect_platform(session: AsyncSession, conn: PlatformConnection) -> str:
    """Сброс OAuth; при незавершённой настройке (ключи без токена) — и ключи."""
    had_token = bool(conn.access_token_enc)
    conn.access_token_enc = None
    conn.refresh_token_enc = None
    conn.token_expires_at = None
    conn.external_channel_id = None
    conn.external_channel_name = None
    conn.oauth_device_id = None
    conn.vk_web_access_token_enc = None
    conn.vk_web_refresh_token_enc = None
    conn.vk_web_token_expires_at = None
    conn.connected_at = None
    conn.enabled = False
    conn.status = "disconnected"
    conn.status_message = None
    if had_token:
        await session.commit()
        return "Площадка отключена. Ключи сохранены — «🔗 Подключить аккаунт» для входа снова."
    conn.client_id_enc = None
    conn.client_secret_enc = None
    await session.commit()
    return "Настройка сброшена. Жми «🔗 Подключить аккаунт» — начнёшь с нуля."


async def check_all_platforms(session: AsyncSession, user_id: int) -> list[str]:
    result = await session.execute(
        select(PlatformConnection).where(PlatformConnection.user_id == user_id)
    )
    lines: list[str] = []
    for conn in result.scalars():
        label = PLATFORM_LABELS.get(Platform(conn.platform), conn.platform)
        if not conn.enabled:
            lines.append(f"{label} ⏸ отключена")
            continue
        creds = await get_credentials(session, conn)
        if not creds:
            lines.append(f"{label} ❌ нет ключей приложения")
            continue
        if not conn.access_token_enc:
            lines.append(f"{label} ❌ не авторизован — жми «Подключить» в настройках")
            continue
        token = await get_access_token(session, conn)
        if not token:
            lines.append(f"{label} ❌ {conn.status_message or 'ошибка токена'}")
            continue
        adapter = get_adapter(Platform(conn.platform))
        status = await adapter.check_token(token, creds)
        icon = "✅" if status.ok else "❌"
        lines.append(f"{label} {icon} {status.message}")
        if not status.ok:
            conn.status = "error"
            conn.status_message = status.message
            await session.commit()
    return lines
