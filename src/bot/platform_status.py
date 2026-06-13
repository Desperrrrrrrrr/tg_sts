from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from src.db.database import get_session_factory
from src.db.models import PLATFORM_LABELS, Platform, PlatformConnection, User


@dataclass(frozen=True)
class PlatformLinkStatus:
    connected: bool
    has_keys: bool


async def load_platform_statuses(telegram_id: int) -> dict[str, PlatformLinkStatus]:
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = r.scalar_one_or_none()
        if not user:
            return {p.value: PlatformLinkStatus(False, False) for p in Platform}
        r2 = await session.execute(
            select(PlatformConnection).where(PlatformConnection.user_id == user.id)
        )
        conns = {c.platform: c for c in r2.scalars()}
    statuses: dict[str, PlatformLinkStatus] = {}
    for p in Platform:
        conn = conns.get(p.value)
        if conn and conn.access_token_enc:
            statuses[p.value] = PlatformLinkStatus(connected=True, has_keys=True)
        elif conn and conn.client_id_enc:
            statuses[p.value] = PlatformLinkStatus(connected=False, has_keys=True)
        else:
            statuses[p.value] = PlatformLinkStatus(connected=False, has_keys=False)
    return statuses


def platform_status_icon(status: PlatformLinkStatus) -> str:
    if status.connected:
        return "🟢"
    if status.has_keys:
        return "🟡"
    return "⚪"


def platform_button_label(p: Platform, status: PlatformLinkStatus) -> str:
    return f"{platform_status_icon(status)} {PLATFORM_LABELS[p]}"


def parse_platform_button(text: str) -> Platform | None:
    for p in Platform:
        if text.endswith(PLATFORM_LABELS[p]) or f" {PLATFORM_LABELS[p]}" in text:
            return p
    return None


def connected_summary(statuses: dict[str, PlatformLinkStatus]) -> str:
    connected = [
        PLATFORM_LABELS[p]
        for p in Platform
        if statuses.get(p.value, PlatformLinkStatus(False, False)).connected
    ]
    if not connected:
        return "Пока ни одна площадка не подключена."
    return "Подключено: <b>" + ", ".join(connected) + "</b>"
