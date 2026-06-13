from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Platform(str, enum.Enum):
    TWITCH = "twitch"
    KICK = "kick"
    YOUTUBE = "youtube"
    VK = "vk"
    TROVO = "trovo"


PLATFORM_LABELS: dict[Platform, str] = {
    Platform.TWITCH: "Twitch",
    Platform.KICK: "Kick",
    Platform.YOUTUBE: "YouTube",
    Platform.VK: "VK Video Live",
    Platform.TROVO: "Trovo",
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    platforms: Mapped[list[PlatformConnection]] = relationship(back_populates="user")
    announce_target: Mapped[AnnounceTarget | None] = relationship(back_populates="user", uselist=False)
    sessions: Mapped[list[StreamSession]] = relationship(back_populates="user")


class PlatformConnection(Base):
    __tablename__ = "platform_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    external_channel_id: Mapped[str | None] = mapped_column(String(128))
    external_channel_name: Mapped[str | None] = mapped_column(String(256))
    client_id_enc: Mapped[str | None] = mapped_column(Text)
    client_secret_enc: Mapped[str | None] = mapped_column(Text)
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="disconnected")
    status_message: Mapped[str | None] = mapped_column(String(512))
    oauth_device_id: Mapped[str | None] = mapped_column(String(128))
    vk_web_access_token_enc: Mapped[str | None] = mapped_column(Text)
    vk_web_refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    vk_web_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="platforms")


class AnnounceTarget(Base):
    """Канал или группа, куда бот постит анонсы."""

    __tablename__ = "announce_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    chat_title: Mapped[str | None] = mapped_column(String(256))

    user: Mapped[User] = relationship(back_populates="announce_target")


class GameMapping(Base):
    """Кэш: единое название игры → ID категории на площадке."""

    __tablename__ = "game_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    game_query: Mapped[str] = mapped_column(String(256), index=True)
    platform: Mapped[str] = mapped_column(String(32))
    category_id: Mapped[str] = mapped_column(String(128))
    category_name: Mapped[str] = mapped_column(String(256))


class StreamSession(Base):
    __tablename__ = "stream_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    game_name: Mapped[str | None] = mapped_column(String(256))
    title: Mapped[str | None] = mapped_column(String(512))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    peak_viewers: Mapped[int | None] = mapped_column(default=0)
    live_message_id: Mapped[int | None] = mapped_column(BigInteger)
    end_message_id: Mapped[int | None] = mapped_column(BigInteger)
    end_summary: Mapped[str | None] = mapped_column(Text)
    next_stream_hint: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="sessions")
