from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from src.api.oauth import create_oauth_state
from src.bot.platform_instructions import client_id_prompt, client_secret_prompt, setup_instructions
from src.bot.platform_status import (
    PlatformLinkStatus,
    connected_summary,
    load_platform_statuses,
    platform_button_label,
)
from src.bot.reply_keyboards import (
    BTN_ADD_PLATFORM,
    BTN_ANNOUNCE,
    BTN_BACK,
    BTN_CONNECT,
    BTN_GAME,
    BTN_GAME_ALL,
    BTN_KEYS,
    BTN_PLATFORMS,
    BTN_SETTINGS,
    BTN_STATUS,
    BTN_TITLE,
    BTN_TITLE_ALL,
    ALL_MENU_BUTTONS,
    main_keyboard,
    persistent_keyboard,
    platform_keyboard,
)
from src.db.database import get_session_factory
from src.db.models import PLATFORM_LABELS, Platform, PlatformConnection, User
from src.platforms.registry import get_adapter
from src.services.platform_creds import save_app_credentials
from src.services.token_manager import verify_platform_connection
from src.services.vk_session import parse_vk_session_auth, save_vk_web_session
from src.services.vk_slug import parse_vk_channel_slug, vk_needs_slug
from src.services.public_url import (
    needs_https_for_oauth,
    oauth_https_hint,
    public_base_url_configured,
    public_url_setup_hint,
    redirect_url_for,
)

router = Router()


class OnboardingStates(StatesGroup):
    pick_platforms = State()
    client_id = State()
    client_secret = State()
    wait_oauth = State()
    vk_channel_slug = State()
    vk_web_token = State()
    wait_announce = State()


def _platform_pick_label(p: Platform, status: PlatformLinkStatus, selected: bool) -> str:
    line = platform_button_label(p, status)
    if status.connected:
        line += " — подключён"
    elif status.has_keys:
        line += " — не авторизован"
    else:
        line += " — не подключён"
    if selected:
        line += " ☑️"
    return line


def _platform_pick_keyboard(
    selected: set[str],
    statuses: dict[str, PlatformLinkStatus],
) -> InlineKeyboardMarkup:
    rows = []
    for p in Platform:
        status = statuses.get(p.value, PlatformLinkStatus(False, False))
        rows.append([
            InlineKeyboardButton(
                text=_platform_pick_label(p, status, p.value in selected),
                callback_data=f"ob:toggle:{p.value}",
            )
        ])
    rows.append([InlineKeyboardButton(text="Готово →", callback_data="ob:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def start_single_platform_setup(message: Message, state: FSMContext, plat: Platform) -> None:
    await state.update_data(
        selected_platforms=[plat.value],
        setup_queue=[plat.value],
        setup_index=0,
        current_platform=plat.value,
    )
    await _begin_platform_setup(message, state)


async def finish_onboarding_skip_announce(message: Message, state: FSMContext) -> dict:
    """Завершить мастер без канала анонсов (onboarding_complete=True)."""
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = r.scalar_one_or_none()
        if user:
            user.onboarding_complete = True
            await session.commit()
    statuses = await load_platform_statuses(message.from_user.id)
    await state.clear()
    return statuses


async def _dispatch_menu_button(message: Message, state: FSMContext, text: str) -> None:
    from src.bot.handlers.menu import (
        btn_add_platform,
        btn_all,
        btn_announce,
        btn_back,
        btn_connect,
        btn_platform,
        btn_platform_game,
        btn_platform_title,
        btn_platforms,
        btn_settings,
        btn_status,
    )
    from src.bot.platform_status import parse_platform_button

    if parse_platform_button(text):
        await btn_platform(message, state)
        return
    handlers = {
        BTN_STATUS: btn_status,
        BTN_SETTINGS: btn_settings,
        BTN_PLATFORMS: btn_platforms,
        BTN_ADD_PLATFORM: btn_add_platform,
        BTN_ANNOUNCE: btn_announce,
        BTN_BACK: btn_back,
        BTN_GAME_ALL: btn_all,
        BTN_TITLE_ALL: btn_all,
        BTN_CONNECT: btn_connect,
        BTN_KEYS: btn_connect,
        BTN_GAME: btn_platform_game,
        BTN_TITLE: btn_platform_title,
    }
    handler = handlers.get(text)
    if handler:
        await handler(message, state)


async def start_onboarding(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(OnboardingStates.pick_platforms)
    await state.update_data(selected_platforms=[], setup_queue=[], setup_index=0)
    statuses = await load_platform_statuses(message.from_user.id)
    if not public_base_url_configured():
        await message.answer(public_url_setup_hint(), parse_mode="HTML")
    else:
        from src.config import get_settings

        await message.answer(
            f"✅ Адрес сервера: <code>{get_settings().public_base_url}</code>\n"
            f"{connected_summary(statuses)}",
            parse_mode="HTML",
        )
        if needs_https_for_oauth():
            await message.answer(oauth_https_hint(), parse_mode="HTML")
    await message.answer(
        "Шаг 1 из 4 — отметь площадки для настройки (☑️), затем «Готово →»:\n\n"
        "🟢 подключён · 🟡 ключи без входа · ⚪ не настроен",
        reply_markup=_platform_pick_keyboard(set(), statuses),
    )
    has_connected = any(s.connected for s in statuses.values())
    await message.answer(
        "Меню внизу 👇",
        reply_markup=main_keyboard(statuses) if has_connected else persistent_keyboard(),
    )


@router.callback_query(F.data.startswith("ob:toggle:"))
async def toggle_platform_pick(cb: CallbackQuery, state: FSMContext) -> None:
    plat = cb.data.split(":")[2]
    data = await state.get_data()
    selected: list[str] = data.get("selected_platforms", [])
    if plat in selected:
        selected.remove(plat)
    else:
        selected.append(plat)
    await state.update_data(selected_platforms=selected)
    statuses = await load_platform_statuses(cb.from_user.id)
    await cb.message.edit_reply_markup(
        reply_markup=_platform_pick_keyboard(set(selected), statuses),
    )
    await cb.answer()


@router.callback_query(F.data == "ob:done")
async def platforms_picked(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected: list[str] = data.get("selected_platforms", [])
    if not selected:
        await cb.answer("Выбери хотя бы одну площадку", show_alert=True)
        return
    await state.update_data(setup_queue=selected, setup_index=0)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer()
    await _begin_platform_setup(cb.message, state)


async def _begin_platform_setup(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    queue: list[str] = data["setup_queue"]
    idx: int = data["setup_index"]
    if idx >= len(queue):
        await _ask_announce_channel(message, state)
        return
    plat = Platform(queue[idx])
    await state.update_data(current_platform=plat.value)
    if not public_base_url_configured():
        await message.answer(public_url_setup_hint(), parse_mode="HTML")
        return
    await state.set_state(OnboardingStates.client_id)
    step = data.get("setup_index", 0) + 1
    total = len(queue)
    await message.answer(
        f"<b>Шаг 2/{total + 2} — {PLATFORM_LABELS[plat]}</b>\n\n{setup_instructions(plat)}",
        parse_mode="HTML",
    )
    await message.answer(client_id_prompt(plat), parse_mode="HTML")


@router.message(OnboardingStates.client_id)
async def on_client_id(message: Message, state: FSMContext) -> None:
    await state.update_data(client_id=message.text.strip())
    await state.set_state(OnboardingStates.client_secret)
    data = await state.get_data()
    plat = Platform(data["current_platform"])
    await message.answer(client_secret_prompt(plat), parse_mode="HTML")


@router.message(OnboardingStates.client_secret)
async def on_client_secret(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    plat = Platform(data["current_platform"])
    client_id = data["client_id"]
    client_secret = message.text.strip()

    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = r.scalar_one()
        r2 = await session.execute(
            select(PlatformConnection).where(
                PlatformConnection.user_id == user.id,
                PlatformConnection.platform == plat.value,
            )
        )
        conn = r2.scalar_one_or_none()
        if not conn:
            conn = PlatformConnection(user_id=user.id, platform=plat.value)
            session.add(conn)
            await session.flush()
        save_app_credentials(conn, client_id, client_secret)
        await session.commit()

    from src.platforms.credentials import OAuthCredentials

    adapter = get_adapter(plat)
    creds = OAuthCredentials(client_id=client_id, client_secret=client_secret)
    if not public_base_url_configured():
        await message.answer(public_url_setup_hint(), parse_mode="HTML")
        return

    oauth_state = create_oauth_state(message.from_user.id, plat)
    url = adapter.get_oauth_url(oauth_state, creds)
    if not url:
        await message.answer("Не удалось собрать ссылку авторизации. Проверь Client ID/Secret.")
        return

    await state.set_state(OnboardingStates.wait_oauth)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Я авторизовался", callback_data="ob:oauth_ok")]]
    )
    auth_hint = ""
    if plat == Platform.KICK:
        auth_hint = "Ссылка должна начинаться с <code>https://id.kick.com/oauth/authorize</code>\n\n"
    elif plat == Platform.VK:
        auth_hint = (
            "Ссылка: <code>https://live.vkvideo.ru/app/oauth2/authorize</code> "
            "(DevAPI, не id.vk.ru и не oauth.vk.com)\n\n"
        )
    await message.answer(
        f"Ключи сохранены.\n\n"
        f"Теперь авторизуй аккаунт на {PLATFORM_LABELS[plat]}:\n"
        f"{auth_hint}"
        f"<code>{url}</code>\n\n"
        f"После «Разрешить» в браузере должна быть страница «✅ подключён».\n"
        f"Тогда нажми кнопку ниже — бот проверит токен через API.",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.callback_query(F.data == "ob:oauth_ok")
async def oauth_done(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    plat = Platform(data["current_platform"])
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == cb.from_user.id))
        user = r.scalar_one()
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
            await cb.answer("OAuth OK!")
            await cb.message.answer(
                "Последний шаг для VK — <b>slug канала</b>.\n\n"
                "Это часть URL после <code>live.vkvideo.ru/</code>\n"
                "Пример: <code>desper</code> или ссылка на канал целиком.",
                parse_mode="HTML",
            )
            return
        already_done = user.onboarding_complete

    await cb.answer("Проверено!")
    next_idx = data.get("setup_index", 0) + 1
    queue: list[str] = data.get("setup_queue", [])
    if next_idx >= len(queue):
        if already_done:
            statuses = await load_platform_statuses(cb.from_user.id)
            await state.clear()
            await cb.message.answer(
                f"✅ <b>{PLATFORM_LABELS[plat]} подключён!</b>\n{detail}",
                parse_mode="HTML",
                reply_markup=main_keyboard(statuses),
            )
            return
        await _ask_announce_channel(cb.message, state)
        return
    await state.update_data(setup_index=next_idx)
    await _begin_platform_setup(cb.message, state)


@router.message(OnboardingStates.vk_channel_slug)
async def vk_channel_slug(message: Message, state: FSMContext) -> None:
    slug = parse_vk_channel_slug(message.text or "")
    if not slug or len(slug) < 2:
        await message.answer("Нужен slug канала, например: <code>desper</code>", parse_mode="HTML")
        return
    data = await state.get_data()
    plat = Platform(data.get("current_platform", Platform.VK.value))
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = r.scalar_one()
        r2 = await session.execute(
            select(PlatformConnection).where(
                PlatformConnection.user_id == user.id,
                PlatformConnection.platform == plat.value,
            )
        )
        conn = r2.scalar_one_or_none()
        if not conn:
            await message.answer("Сначала подключи VK в настройках.")
            return
        conn.external_channel_id = slug
        conn.external_channel_name = slug
        await session.commit()
        ok, detail = await verify_platform_connection(session, conn)
        already_done = user.onboarding_complete
    if not ok:
        await message.answer(detail, parse_mode="HTML")
        return
    await message.answer(f"✅ VK канал: <b>@{slug}</b>", parse_mode="HTML")
    await message.answer(
        "Для <b>смены игры и названия</b> на VK нужен session-токен из браузера.\n\n"
        "1. Открой <code>live.vkvideo.ru</code> под своим аккаунтом\n"
        "2. F12 → Application → Local Storage → live.vkvideo.ru → ключ <code>auth</code>\n"
        "3. Скопируй значение целиком и отправь сюда\n\n"
        "Или /skip — тогда VK только для поиска игр, смена вручную на сайте.",
        parse_mode="HTML",
    )
    await state.set_state(OnboardingStates.vk_web_token)


async def _continue_platform_setup(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    next_idx = data.get("setup_index", 0) + 1
    queue: list[str] = data.get("setup_queue", [])
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = r.scalar_one()
        already_done = user.onboarding_complete
    if next_idx >= len(queue):
        if already_done:
            statuses = await load_platform_statuses(message.from_user.id)
            await state.clear()
            await message.answer("Главное меню", reply_markup=main_keyboard(statuses))
            return
        await _ask_announce_channel(message, state)
        return
    await state.update_data(setup_index=next_idx)
    await _begin_platform_setup(message, state)


@router.message(OnboardingStates.vk_web_token)
async def vk_web_token(message: Message, state: FSMContext) -> None:
    if (message.text or "").strip().lower() in {"/skip", "skip"}:
        data = await state.get_data()
        if data.get("setup_queue"):
            await message.answer("Ок, session-токен можно добавить позже: «🔑 Session-токен VK».")
            await _continue_platform_setup(message, state)
        else:
            await state.set_state(None)
            statuses = await load_platform_statuses(message.from_user.id)
            st = statuses.get(Platform.VK.value, PlatformLinkStatus(False, False))
            await message.answer("Отменено.", reply_markup=platform_keyboard(st, platform=Platform.VK))
        return
    data = await state.get_data()
    plat = Platform(data.get("current_platform", Platform.VK.value))
    try:
        parsed = parse_vk_session_auth(message.text or "")
    except (json.JSONDecodeError, ValueError) as e:
        await message.answer(
            f"Не разобрал JSON: {e}\n\nНужно значение ключа <code>auth</code> из localStorage.",
            parse_mode="HTML",
        )
        return
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = r.scalar_one()
        r2 = await session.execute(
            select(PlatformConnection).where(
                PlatformConnection.user_id == user.id,
                PlatformConnection.platform == plat.value,
            )
        )
        conn = r2.scalar_one_or_none()
        if not conn:
            await message.answer("Сначала подключи VK.")
            return
        await save_vk_web_session(session, conn, parsed)
    await message.answer("✅ Session-токен VK сохранён — смена игры через бота должна работать.")
    if data.get("setup_queue"):
        await _continue_platform_setup(message, state)
    else:
        await state.set_state(None)
        statuses = await load_platform_statuses(message.from_user.id)
        st = statuses.get(Platform.VK.value, PlatformLinkStatus(False, False))
        await message.answer("Готово.", reply_markup=platform_keyboard(st, platform=Platform.VK))


async def _ask_announce_channel(message: Message, state: FSMContext) -> None:
    await state.set_state(OnboardingStates.wait_announce)
    statuses = await load_platform_statuses(message.from_user.id)
    await message.answer(
        "Последний шаг — канал для анонсов.\n\n"
        "Перешли сообщение из канала/группы, куда постить анонсы.\n"
        "Бот должен быть там админом.\n\n"
        "Пропустить: <b>/skip</b>, <b>« Назад</b> или любая кнопка меню.\n"
        "Позже: ⚙️ → 📢 Канал анонсов.",
        parse_mode="HTML",
        reply_markup=main_keyboard(statuses),
    )


@router.message(F.text == BTN_BACK, StateFilter(OnboardingStates))
async def onboarding_back(message: Message, state: FSMContext) -> None:
    statuses = await finish_onboarding_skip_announce(message, state)
    await message.answer("Главное меню", reply_markup=main_keyboard(statuses))


@router.message(
    F.text.func(lambda t: t in ALL_MENU_BUTTONS and t != BTN_BACK),
    StateFilter(
        OnboardingStates.client_id,
        OnboardingStates.client_secret,
        OnboardingStates.wait_oauth,
    ),
)
async def onboarding_abort_to_menu(message: Message, state: FSMContext) -> None:
    statuses = await finish_onboarding_skip_announce(message, state)
    await message.answer("Вышел из настройки.", reply_markup=main_keyboard(statuses))
    await _dispatch_menu_button(message, state, message.text)


@router.message(OnboardingStates.wait_announce, F.forward_from_chat)
async def finish_onboarding_forward(message: Message, state: FSMContext) -> None:
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = r.scalar_one()
        from src.db.models import AnnounceTarget

        chat = message.forward_from_chat
        tr = await session.execute(select(AnnounceTarget).where(AnnounceTarget.user_id == user.id))
        target = tr.scalar_one_or_none()
        if target:
            target.chat_id = chat.id
            target.chat_title = chat.title
        else:
            session.add(AnnounceTarget(user_id=user.id, chat_id=chat.id, chat_title=chat.title))
        user.onboarding_complete = True
        await session.commit()

    statuses = await load_platform_statuses(message.from_user.id)
    await state.clear()
    await message.answer(
        f"✅ Анонсы в: {chat.title or chat.id}",
        reply_markup=main_keyboard(statuses),
    )


@router.message(
    OnboardingStates.wait_announce,
    F.text.in_({"/skip"} | set(ALL_MENU_BUTTONS)),
)
async def wait_announce_escape(message: Message, state: FSMContext) -> None:
    statuses = await finish_onboarding_skip_announce(message, state)
    if message.text == "/skip" or message.text == BTN_BACK:
        await message.answer(
            "✅ Ок. Канал анонсов настроишь позже в ⚙️ → 📢",
            reply_markup=main_keyboard(statuses),
        )
        return
    await message.answer("Главное меню", reply_markup=main_keyboard(statuses))
    await _dispatch_menu_button(message, state, message.text)


@router.message(OnboardingStates.wait_announce)
async def finish_onboarding_unknown(message: Message, state: FSMContext) -> None:
    statuses = await load_platform_statuses(message.from_user.id)
    await message.answer(
        "Перешли сообщение из канала/группы или нажми /skip, « Назад», 📡 Площадки…",
        reply_markup=main_keyboard(statuses),
    )

