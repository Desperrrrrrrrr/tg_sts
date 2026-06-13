from __future__ import annotations

import json
from datetime import timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import PlatformConnection
from src.services.crypto import decrypt_token, encrypt_token
from src.utils.time import as_utc, utc_now

_VK_WEB_REFRESH = "https://api.live.vkvideo.ru/oauth/token/"
_BROWSER_HEADERS = {
    "Origin": "https://live.vkvideo.ru",
    "Referer": "https://live.vkvideo.ru/",
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
}


def parse_vk_session_auth(text: str) -> dict[str, str | int]:
    """Парсит auth из localStorage live.vkvideo.ru (поле auth)."""
    raw = text.strip()
    if not raw:
        raise ValueError("Пустой текст")
    data = json.loads(raw)
    if isinstance(data, dict) and "accessToken" in data:
        auth = data
    elif isinstance(data, dict) and "auth" in data:
        inner = data["auth"]
        auth = json.loads(inner) if isinstance(inner, str) else inner
    else:
        raise ValueError("Нужен JSON с accessToken и refreshToken")
    access = auth.get("accessToken") or auth.get("access_token")
    refresh = auth.get("refreshToken") or auth.get("refresh_token")
    if not access or not refresh:
        raise ValueError("В JSON нет accessToken / refreshToken")
    expires_at = auth.get("expiresAt") or auth.get("expires_at")
    expires_in = auth.get("expires_in")
    return {
        "access_token": str(access),
        "refresh_token": str(refresh),
        "expires_at": int(expires_at) if expires_at else 0,
        "expires_in": int(expires_in) if expires_in else 0,
    }


async def save_vk_web_session(
    session: AsyncSession,
    conn: PlatformConnection,
    parsed: dict[str, str | int],
) -> None:
    conn.vk_web_access_token_enc = encrypt_token(str(parsed["access_token"]))
    conn.vk_web_refresh_token_enc = encrypt_token(str(parsed["refresh_token"]))
    expires_at = int(parsed.get("expires_at") or 0)
    if expires_at > 1_000_000_000_000:
        expires_at = expires_at // 1000
    if expires_at > 0:
        from datetime import datetime, timezone

        conn.vk_web_token_expires_at = datetime.fromtimestamp(expires_at, tz=timezone.utc)
    elif parsed.get("expires_in"):
        conn.vk_web_token_expires_at = utc_now() + timedelta(seconds=int(parsed["expires_in"]))
    else:
        conn.vk_web_token_expires_at = utc_now() + timedelta(hours=12)
    await session.commit()


async def get_vk_web_access_token(session: AsyncSession, conn: PlatformConnection) -> str | None:
    if not conn.vk_web_access_token_enc:
        return None
    token = decrypt_token(conn.vk_web_access_token_enc)
    expires = as_utc(conn.vk_web_token_expires_at)
    if expires and expires > utc_now():
        return token
    if not conn.vk_web_refresh_token_enc:
        return token
    refresh = decrypt_token(conn.vk_web_refresh_token_enc)
    async with httpx.AsyncClient() as client:
        body = {
            "response_type": "code",
            "refresh_token": refresh,
            "grant_type": "refresh_token",
            "device_id": conn.oauth_device_id or "streams_web",
            "device_os": "streams_web",
        }
        r = await client.post(_VK_WEB_REFRESH, data=body, headers=_BROWSER_HEADERS)
        if r.status_code >= 400:
            return token
        data = r.json()
        conn.vk_web_access_token_enc = encrypt_token(data["access_token"])
        if data.get("refresh_token"):
            conn.vk_web_refresh_token_enc = encrypt_token(data["refresh_token"])
        conn.vk_web_token_expires_at = utc_now() + timedelta(seconds=int(data.get("expires_in", 3600)))
        await session.commit()
        return data["access_token"]
