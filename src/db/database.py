from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings
from src.db.models import Base

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, echo=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


def _migrate(sync_conn) -> None:
    import sqlalchemy

    insp = sqlalchemy.inspect(sync_conn)
    if not insp.has_table("platform_connections"):
        return
    cols = {c["name"] for c in insp.get_columns("platform_connections")}
    if "oauth_device_id" not in cols:
        sync_conn.execute(
            sqlalchemy.text("ALTER TABLE platform_connections ADD COLUMN oauth_device_id VARCHAR(128)")
        )
        cols.add("oauth_device_id")
    for col, ddl in (
        ("vk_web_access_token_enc", "TEXT"),
        ("vk_web_refresh_token_enc", "TEXT"),
        ("vk_web_token_expires_at", "DATETIME"),
    ):
        if col not in cols:
            sync_conn.execute(
                sqlalchemy.text(f"ALTER TABLE platform_connections ADD COLUMN {col} {ddl}")
            )


async def init_db() -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
