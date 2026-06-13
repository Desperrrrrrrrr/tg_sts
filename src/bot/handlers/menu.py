from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from src.api.oauth import create_oauth_state
from src.bot.handlers.onboarding import OnboardingStates, start_onboarding, start_single_platform_setup
from src.bot.platform_status import PlatformLinkStatus, load_platform_statuses, parse_platform_button
from src.bot.reply_keyboards import (
    BTN_ADD_PLATFORM,
    BTN_ANNOUNCE,
    BTN_BACK,
    BTN_CONNECT,
    BTN_DISCONNECT,
    BTN_GAME,
    BTN_GAME_ALL,
    BTN_KEYS,
    BTN_PLATFORMS,
    BTN_SETTINGS,
    BTN_STATUS,
    BTN_TITLE,
    BTN_TITLE_ALL,
    BTN_VK_SESSION,
    main_keyboard,
    persistent_keyboard,
    platform_keyboard,
    platforms_manage_keyboard,
    settings_keyboard,
)
from src.db.database import get_session_factory
from src.db.models import PLATFORM_LABELS, Platform, PlatformConnection, User
from src.platforms.registry import get_adapter
from src.services.platform_creds import get_credentials
from src.services.token_manager import check_all_platforms, disconnect_platform, verify_platform_connection
from src.services.vk_slug import vk_needs_slug

router = Router()


class MenuStates(StatesGroup):
    browsing_platforms = State()


class ActionStates(StatesGroup):
    waiting_game = State()
    waiting_game_refine = State()
    waiting_game_title = State()
    waiting_title = State()


async def _user(session, telegram_id: int) -> User | None:
    r = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return r.scalar_one_or_none()


async def _reply_main(message: Message) -> None:
    statuses = await load_platform_statuses(message.from_user.id)
    await message.answer("Главное меню", reply_markup=main_keyboard(statuses))


@router.message(F.text == BTN_STATUS)
async def btn_status(message: Message) -> None:
    factory = get_session_factory()
    async with factory() as session:
        user = await _user(session, message.from_user.id)
        if not user:
            await message.answer("Сначала /start")
            return
        lines = await check_all_platforms(session, user.id)
    statuses = await load_platform_statuses(message.from_user.id)
    await message.answer(
        "Статус площадок:\n\n" + ("\n".join(lines) if lines else "Ничего не подключено."),
        reply_markup=main_keyboard(statuses),
    )


@router.message(F.text == BTN_SETTINGS)
async def btn_settings(message: Message) -> None:
    await message.answer(
        "⚙️ <b>Настройки</b>\n\n"
        "• <b>➕ Добавить площадку</b> — мастер настройки (как /setup)\n"
        "• <b>📢 Канал анонсов</b> — перешли сообщение из канала/группы\n"
        "• Площадка → <b>🔗 Подключить аккаунт</b>",
        parse_mode="HTML",
        reply_markup=settings_keyboard(),
    )


@router.message(F.text == BTN_PLATFORMS, ~StateFilter(OnboardingStates))
async def btn_platforms(message: Message, state: FSMContext) -> None:
    await state.set_state(MenuStates.browsing_platforms)
    statuses = await load_platform_statuses(message.from_user.id)
    await message.answer(
        "📡 <b>Площадки</b>\n\n"
        "🟢 подключён · 🟡 ключи без входа · ⚪ не настроен\n\n"
        "Выбери площадку или «➕ Добавить площадку».",
        parse_mode="HTML",
        reply_markup=platforms_manage_keyboard(statuses),
    )


@router.message(F.text == BTN_ADD_PLATFORM, ~StateFilter(OnboardingStates))
async def btn_add_platform(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    await start_onboarding(message, state)


@router.message(F.text == BTN_ANNOUNCE)
async def btn_announce(message: Message) -> None:
    await message.answer(
        "📢 Перешли мне любое сообщение из канала или группы для анонсов.\n"
        "Бот должен быть там админом (публикация + удаление сообщений).",
        reply_markup=settings_keyboard(),
    )


@router.message(F.text == BTN_BACK)
async def btn_back(message: Message, state: FSMContext) -> None:
    await state.update_data(target_platform=None)
    await state.set_state(None)
    await _reply_main(message)


@router.message(F.text.in_({BTN_GAME_ALL, BTN_TITLE_ALL}))
async def btn_all(message: Message, state: FSMContext) -> None:
    await state.update_data(target_platform="all")
    if message.text == BTN_GAME_ALL:
        await state.set_state(ActionStates.waiting_game)
        await message.answer("Напиши название игры:")
    else:
        await state.set_state(ActionStates.waiting_title)
        await message.answer("Напиши новое название стрима:")


@router.message(
    F.text.func(lambda t: parse_platform_button(t) is not None),
    ~StateFilter(OnboardingStates),
)
async def btn_platform(message: Message, state: FSMContext) -> None:
    plat = parse_platform_button(message.text)
    if not plat:
        return
    await state.update_data(target_platform=plat.value)
    await state.set_state(None)
    statuses = await load_platform_statuses(message.from_user.id)
    status = statuses.get(plat.value, PlatformLinkStatus(False, False))
    if status.connected:
        hint = "✅ Подключён. «🔗 Подключить аккаунт» — новая ссылка OAuth. «🔌 Отключить» — выйти."
    elif status.has_keys:
        hint = (
            "🟡 Ключи есть, вход не завершён.\n"
            "«🔗 Подключить аккаунт» — ссылка OAuth.\n"
            "«🔌 Отключить» — сбросить и начать заново."
        )
    else:
        hint = "«🔗 Подключить аккаунт» — инструкция, ключи и вход (всё по шагам)."
    await message.answer(
        f"<b>{PLATFORM_LABELS[plat]}</b>\n{hint}",
        parse_mode="HTML",
        reply_markup=platform_keyboard(status, platform=plat),
    )


@router.message(F.text == BTN_GAME)
async def btn_platform_game(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("target_platform") or data["target_platform"] == "all":
        await message.answer("Сначала выбери площадку в меню.")
        return
    await state.set_state(ActionStates.waiting_game)
    await message.answer("Напиши название игры:")


@router.message(F.text == BTN_TITLE)
async def btn_platform_title(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("target_platform") or data["target_platform"] == "all":
        await message.answer("Сначала выбери площадку в меню.")
        return
    await state.set_state(ActionStates.waiting_title)
    await message.answer("Напиши новое название стрима:")


@router.message(
    F.text.in_({BTN_CONNECT, BTN_KEYS}),
    ~StateFilter(OnboardingStates),
)
async def btn_connect(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    plat_value = data.get("target_platform")
    if not plat_value or plat_value == "all":
        await message.answer("Сначала выбери площадку в «📡 Площадки».")
        return
    plat = Platform(plat_value)
    factory = get_session_factory()
    async with factory() as session:
        user = await _user(session, message.from_user.id)
        if not user:
            return
        r = await session.execute(
            select(PlatformConnection).where(
                PlatformConnection.user_id == user.id,
                PlatformConnection.platform == plat.value,
            )
        )
        conn = r.scalar_one_or_none()
        creds = await get_credentials(session, conn) if conn else None
    if not creds:
        await start_single_platform_setup(message, state, plat)
        return
    oauth_state = create_oauth_state(message.from_user.id, plat)
    url = get_adapter(plat).get_oauth_url(oauth_state, creds)
    auth_hint = ""
    if plat == Platform.KICK:
        auth_hint = "\n\nСсылка должна начинаться с <code>https://id.kick.com/oauth/authorize</code>"
    elif plat == Platform.VK:
        auth_hint = (
            "\n\nСсылка: <code>https://live.vkvideo.ru/app/oauth2/authorize</code> "
            "(OAuth DevAPI, не id.vk.ru)."
        )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Проверить авторизацию", callback_data=f"menu:oauth_ok:{plat.value}")]
        ]
    )
    await message.answer(
        f"Авторизуйся на {PLATFORM_LABELS[plat]}:\n\n<code>{url}</code>{auth_hint}\n\n"
        f"После «Разрешить» в браузере — страница «✅ подключён». Затем «Проверить авторизацию».",
        parse_mode="HTML",
        reply_markup=kb,
    )
    statuses = await load_platform_statuses(message.from_user.id)
    st = statuses.get(plat.value, PlatformLinkStatus(False, False))
    await message.answer("Меню площадки:", reply_markup=platform_keyboard(st, platform=plat))


@router.message(F.text == BTN_DISCONNECT, ~StateFilter(OnboardingStates))
async def btn_disconnect(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    plat_value = data.get("target_platform")
    if not plat_value or plat_value == "all":
        await message.answer("Сначала выбери площадку в «📡 Площадки».")
        return
    plat = Platform(plat_value)
    factory = get_session_factory()
    async with factory() as session:
        user = await _user(session, message.from_user.id)
        if not user:
            return
        r = await session.execute(
            select(PlatformConnection).where(
                PlatformConnection.user_id == user.id,
                PlatformConnection.platform == plat.value,
            )
        )
        conn = r.scalar_one_or_none()
        if not conn or (not conn.access_token_enc and not conn.client_id_enc):
            await message.answer("Площадка не настроена.")
            return
        msg = await disconnect_platform(session, conn)
    statuses = await load_platform_statuses(message.from_user.id)
    await message.answer(
        f"🔌 <b>{PLATFORM_LABELS[plat]}</b>\n{msg}",
        parse_mode="HTML",
        reply_markup=platform_keyboard(statuses.get(plat.value, PlatformLinkStatus(False, False)), platform=plat),
    )


@router.callback_query(F.data.startswith("menu:oauth_ok:"))
async def menu_oauth_done(cb: CallbackQuery, state: FSMContext) -> None:
    plat_value = cb.data.removeprefix("menu:oauth_ok:")
    try:
        plat = Platform(plat_value)
    except ValueError:
        await cb.answer("Неизвестная площадка", show_alert=True)
        return
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == cb.from_user.id))
        user = r.scalar_one_or_none()
        if not user:
            await cb.answer("Сначала /start", show_alert=True)
            return
        r2 = await session.execute(
            select(PlatformConnection).where(
                PlatformConnection.user_id == user.id,
                PlatformConnection.platform == plat.value,
            )
        )
        conn = r2.scalar_one_or_none()
        if not conn:
            await cb.answer("Сначала отправь ключи приложения.", show_alert=True)
            return
        ok, detail = await verify_platform_connection(session, conn)
    if not ok:
        await cb.answer(detail, show_alert=True)
        return
    if plat == Platform.VK and vk_needs_slug(conn):
        await state.set_state(OnboardingStates.vk_channel_slug)
        await state.update_data(current_platform=plat.value)
        await cb.answer("OAuth OK!")
        await cb.message.answer(
            "VK: укажи <b>slug канала</b> — часть URL после live.vkvideo.ru/\n"
            "Пример: <code>desper</code>",
            parse_mode="HTML",
        )
        return
    await cb.answer("Проверено!")
    statuses = await load_platform_statuses(cb.from_user.id)
    await cb.message.answer(
        f"✅ <b>{PLATFORM_LABELS[plat]} подключён!</b>\n{detail}",
        parse_mode="HTML",
        reply_markup=platform_keyboard(statuses.get(plat.value, PlatformLinkStatus(False, False)), platform=plat),
    )


@router.message(F.text == BTN_VK_SESSION, ~StateFilter(OnboardingStates))
async def btn_vk_session(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("target_platform") != Platform.VK.value:
        await message.answer("Сначала выбери VK Video Live в «📡 Площадки».")
        return
    await state.set_state(OnboardingStates.vk_web_token)
    await state.update_data(current_platform=Platform.VK.value)
    await message.answer(
        "Вставь значение ключа <code>auth</code> из localStorage браузера "
        "(live.vkvideo.ru → F12 → Application → Local Storage).\n\n"
        "/skip — отмена.",
        parse_mode="HTML",
    )


@router.message(ActionStates.waiting_game)
async def on_game_input(message: Message, state: FSMContext) -> None:
    from src.bot.handlers.game_flow import process_game_change

    await process_game_change(message, state, message.text.strip())


@router.message(ActionStates.waiting_game_refine)
async def on_game_refine_input(message: Message, state: FSMContext) -> None:
    from src.bot.handlers.game_flow import process_game_refine

    q = message.text.strip()
    if len(q) < 3:
        await message.answer("Нужно минимум 3 буквы.")
        return
    await process_game_refine(message, state, q)


def is_title_skip(text: str | None) -> bool:
    if not text:
        return False
    t = text.strip().lower()
    return t in {"/skip", "skip", "пропустить", "⏭ пропустить"}


@router.message(ActionStates.waiting_game_title)
async def on_game_title_input(message: Message, state: FSMContext) -> None:
    from src.bot.handlers.game_flow import apply_game_and_title

    title = None if is_title_skip(message.text) else message.text.strip()
    await apply_game_and_title(message, state, title=title)
    await state.set_state(None)


@router.message(ActionStates.waiting_title)
async def on_title_input(message: Message, state: FSMContext) -> None:
    from src.services.stream_ops import update_on_platforms

    data = await state.get_data()
    target = data.get("target_platform", "all")
    pf = None if target == "all" else Platform(target)
    factory = get_session_factory()
    async with factory() as session:
        user = await _user(session, message.from_user.id)
        errors = await update_on_platforms(
            session, user.id, platform_filter=pf, title=message.text.strip()
        )
    statuses = await load_platform_statuses(message.from_user.id)
    await state.set_state(None)
    scope = "везде" if target == "all" else PLATFORM_LABELS[pf]
    if errors:
        await message.answer(
            f"Частично ({scope}):\n" + "\n".join(errors),
            reply_markup=main_keyboard(statuses),
        )
    else:
        await message.answer(
            f"✅ Название обновлено ({scope})",
            reply_markup=main_keyboard(statuses),
        )
