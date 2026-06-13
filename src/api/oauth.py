from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from src.db.database import get_session_factory
from src.db.models import PLATFORM_LABELS, Platform, PlatformConnection, User
from src.platforms.registry import get_adapter
from src.services.oauth_pkce import pop_pkce_verifier
from src.services.platform_creds import get_credentials
from src.services.token_manager import save_oauth_tokens

_oauth_states: dict[str, tuple[int, str, datetime]] = {}


def create_oauth_state(telegram_id: int, platform: Platform) -> str:
    state = secrets.token_urlsafe(24)
    _oauth_states[state] = (telegram_id, platform.value, datetime.now(UTC) + timedelta(minutes=10))
    return state


def create_oauth_app() -> FastAPI:
    app = FastAPI(title="StreamSync OAuth", docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/oauth/{platform}")
    async def oauth_callback(
        platform: str,
        code: str | None = None,
        state: str | None = None,
        device_id: str | None = None,
    ):
        if not code or not state:
            return HTMLResponse("<h1>Ошибка</h1><p>Нет code или state</p>", status_code=400)
        pending = _oauth_states.get(state)
        if not pending:
            return HTMLResponse("<h1>Сессия истекла</h1><p>Начни подключение заново в боте.</p>", status_code=400)
        telegram_id, plat_value, expires = pending
        from src.utils.time import as_utc, utc_now

        if utc_now() > as_utc(expires):
            return HTMLResponse("<h1>Время вышло</h1>", status_code=400)
        if plat_value != platform:
            raise HTTPException(400, "platform mismatch")

        plat = Platform(platform)
        factory = get_session_factory()
        async with factory() as session:
            r = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = r.scalar_one_or_none()
            if not user:
                return HTMLResponse("<h1>Пользователь не найден</h1>", status_code=400)
            r2 = await session.execute(
                select(PlatformConnection).where(
                    PlatformConnection.user_id == user.id,
                    PlatformConnection.platform == platform,
                )
            )
            conn = r2.scalar_one_or_none()
            if not conn:
                return HTMLResponse("<h1>Сначала введи Client ID/Secret в боте</h1>", status_code=400)
            creds = await get_credentials(session, conn)
            if not creds:
                return HTMLResponse("<h1>Нет ключей приложения</h1>", status_code=400)

            adapter = get_adapter(plat)
            exchange_kwargs: dict = {}
            if plat == Platform.KICK:
                verifier = pop_pkce_verifier(state)
                if not verifier:
                    return HTMLResponse(
                        "<h1>Сессия истекла</h1><p>Начни подключение заново в боте.</p>",
                        status_code=400,
                    )
                exchange_kwargs["code_verifier"] = verifier
            try:
                tokens = await adapter.exchange_code(code, creds, **exchange_kwargs)
            except Exception as e:
                return HTMLResponse(
                    f"<h1>Ошибка обмена токена</h1><p>{e}</p>"
                    f"<p>Запроси <b>новую</b> ссылку в боте и пройди OAuth снова.</p>",
                    status_code=500,
                )

            _oauth_states.pop(state, None)
            await save_oauth_tokens(
                session,
                conn,
                access_token=tokens["access_token"],
                refresh_token=tokens.get("refresh_token"),
                expires_in=tokens.get("expires_in"),
                channel_id=tokens["channel_id"],
                channel_name=tokens.get("channel_name", ""),
                oauth_device_id=tokens.get("oauth_device_id"),
            )

        label = PLATFORM_LABELS.get(plat, platform)
        extra = ""
        if plat == Platform.VK and not tokens.get("channel_name"):
            extra = (
                "<p><b>Шаг 2 в Telegram:</b> нажми «Проверить авторизацию» "
                "и отправь <b>slug канала</b> — часть URL после "
                "<code>live.vkvideo.ru/</code> (например <code>desper</code>).</p>"
            )
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
            f"<h1>✅ {label} подключён!</h1>"
            f"<p>Закрой вкладку и вернись в Telegram.</p>{extra}</body></html>"
        )

    return app
