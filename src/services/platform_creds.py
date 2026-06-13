from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.db.models import Platform, PlatformConnection
from src.platforms.credentials import OAuthCredentials
from src.services.crypto import decrypt_token, encrypt_token


def _env_fallback(platform: Platform) -> OAuthCredentials:
    s = get_settings()
    mapping = {
        Platform.TWITCH: (s.twitch_client_id, s.twitch_client_secret),
        Platform.KICK: (s.kick_client_id, s.kick_client_secret),
        Platform.YOUTUBE: (s.youtube_client_id, s.youtube_client_secret),
        Platform.VK: (s.vk_client_id, s.vk_client_secret),
        Platform.TROVO: (s.trovo_client_id, s.trovo_client_secret),
    }
    cid, secret = mapping[platform]
    return OAuthCredentials(client_id=cid or "", client_secret=secret or "")


async def get_credentials(session: AsyncSession, conn: PlatformConnection) -> OAuthCredentials | None:
    if conn.client_id_enc and conn.client_secret_enc:
        return OAuthCredentials(
            client_id=decrypt_token(conn.client_id_enc),
            client_secret=decrypt_token(conn.client_secret_enc),
        )
    creds = _env_fallback(Platform(conn.platform))
    return creds if creds.configured else None


def save_app_credentials(conn: PlatformConnection, client_id: str, client_secret: str) -> None:
    conn.client_id_enc = encrypt_token(client_id.strip())
    conn.client_secret_enc = encrypt_token(client_secret.strip())
