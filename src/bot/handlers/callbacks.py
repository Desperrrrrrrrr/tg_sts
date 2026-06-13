from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from src.api.oauth import create_oauth_state
from src.bot.keyboards import main_menu, platform_actions, platforms_menu
from src.config import get_settings
from src.db.database import get_session_factory
from src.db.models import PLATFORM_LABELS, AnnounceTarget, Platform, PlatformConnection, User
from src.services.token_manager import check_all_platforms

router = Router()


async def _get_user(session, telegram_id: int) -> User | None:
    r = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return r.scalar_one_or_none()


@router.callback_query(F.data == "menu:main")
async def menu_main(cb: CallbackQuery) -> None:
    await cb.message.edit_text("Главное меню:", reply_markup=main_menu())
    await cb.answer()


@router.callback_query(F.data == "menu:platforms")
async def menu_platforms(cb: CallbackQuery) -> None:
    factory = get_session_factory()
    async with factory() as session:
        user = await _get_user(session, cb.from_user.id)
        if not user:
            await cb.answer("Сначала /start", show_alert=True)
            return
        r = await session.execute(
            select(PlatformConnection).where(PlatformConnection.user_id == user.id)
        )
        conns = {c.platform: c.enabled and bool(c.access_token_enc) for c in r.scalars()}
    await cb.message.edit_text("Площадки:", reply_markup=platforms_menu(conns))
    await cb.answer()


@router.callback_query(F.data.startswith("plat:"))
async def platform_detail(cb: CallbackQuery) -> None:
    plat = Platform(cb.data.split(":")[1])
    factory = get_session_factory()
    async with factory() as session:
        user = await _get_user(session, cb.from_user.id)
        r = await session.execute(
            select(PlatformConnection).where(
                PlatformConnection.user_id == user.id,
                PlatformConnection.platform == plat.value,
            )
        )
        conn = r.scalar_one_or_none()
    connected = bool(conn and conn.access_token_enc)
    enabled = conn.enabled if conn else False
    label = PLATFORM_LABELS[plat]
    text = f"<b>{label}</b>\n\n"
    if connected:
        text += f"Канал: {conn.external_channel_name or conn.external_channel_id}\n"
        text += f"Статус: {conn.status_message or '—'}"
    else:
        text += "Не подключена. Нажми «Подключить»."
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=platform_actions(plat, connected, enabled))
    await cb.answer()


@router.callback_query(F.data.startswith("connect:"))
async def connect_platform(cb: CallbackQuery) -> None:
    plat = Platform(cb.data.split(":")[1])
    from src.platforms.registry import get_adapter

    factory = get_session_factory()
    async with factory() as session:
        user = await _get_user(session, cb.from_user.id)
        r = await session.execute(
            select(PlatformConnection).where(
                PlatformConnection.user_id == user.id,
                PlatformConnection.platform == plat.value,
            )
        )
        conn = r.scalar_one_or_none()
        from src.services.platform_creds import get_credentials

        creds = await get_credentials(session, conn) if conn else None
    adapter = get_adapter(plat)
    state = create_oauth_state(cb.from_user.id, plat)
    url = adapter.get_oauth_url(state, creds) if creds else None
    if not url:
        await cb.answer(
            f"Сначала введи Client ID и Secret для {PLATFORM_LABELS[plat]} через /setup",
            show_alert=True,
        )
        return
    await cb.message.answer(
        f"Открой ссылку, авторизуйся на {PLATFORM_LABELS[plat]} и нажми «Разрешить»:\n\n{url}"
    )
    await cb.answer()


@router.callback_query(F.data.startswith("toggle:"))
async def toggle_platform(cb: CallbackQuery) -> None:
    plat = cb.data.split(":")[1]
    factory = get_session_factory()
    async with factory() as session:
        user = await _get_user(session, cb.from_user.id)
        r = await session.execute(
            select(PlatformConnection).where(
                PlatformConnection.user_id == user.id,
                PlatformConnection.platform == plat,
            )
        )
        conn = r.scalar_one_or_none()
        if conn:
            conn.enabled = not conn.enabled
            await session.commit()
    await cb.answer("Готово")
    await menu_platforms(cb)


@router.callback_query(F.data == "menu:status")
async def menu_status(cb: CallbackQuery) -> None:
    factory = get_session_factory()
    async with factory() as session:
        user = await _get_user(session, cb.from_user.id)
        lines = await check_all_platforms(session, user.id)
    text = "Статус площадок:\n\n" + ("\n".join(lines) if lines else "Ничего не подключено.")
    await cb.message.edit_text(text, reply_markup=main_menu())
    await cb.answer()


@router.callback_query(F.data == "menu:announce")
async def menu_announce(cb: CallbackQuery) -> None:
    await cb.message.answer(
        "Перешли мне любое сообщение из канала или группы, куда я должен постить анонсы.\n"
        "Я должен быть там администратором с правом публикации и удаления сообщений."
    )
    await cb.answer()

