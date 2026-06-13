from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select

from src.bot.handlers.menu import ActionStates
from src.bot.handlers.onboarding import (
    OnboardingStates,
    finish_onboarding_skip_announce,
    start_onboarding,
)
from src.bot.platform_status import load_platform_statuses
from src.bot.reply_keyboards import main_keyboard
from src.db.database import get_session_factory
from src.db.models import User
from src.services.token_manager import check_all_platforms

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = r.scalar_one_or_none()
        if not user:
            user = User(telegram_id=message.from_user.id)
            session.add(user)
            await session.commit()

        onboarding_done = user.onboarding_complete

    statuses = await load_platform_statuses(message.from_user.id)
    has_connected = any(s.connected for s in statuses.values())

    if not onboarding_done and not has_connected:
        await start_onboarding(message, state)
        return

    await state.clear()

    if not onboarding_done and has_connected:
        await finish_onboarding_skip_announce(message, state)
        statuses = await load_platform_statuses(message.from_user.id)
        await message.answer(
            "Есть подключённые площадки. Донастрой остальное через «📡 Площадки» или «➕ Добавить площадку».",
            reply_markup=main_keyboard(statuses),
        )
        return

    await message.answer(
        "Снова привет! Выбери действие кнопками ниже.",
        reply_markup=main_keyboard(statuses),
    )


@router.message(Command("setup"))
async def cmd_setup(message: Message, state: FSMContext) -> None:
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = r.scalar_one_or_none()
        if not user:
            user = User(telegram_id=message.from_user.id)
            session.add(user)
            await session.commit()
    await start_onboarding(message, state)


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = r.scalar_one_or_none()
        if not user:
            await message.answer("Сначала /start")
            return
        lines = await check_all_platforms(session, user.id)
    statuses = await load_platform_statuses(message.from_user.id)
    await message.answer(
        "Статус:\n\n" + ("\n".join(lines) if lines else "Ничего не подключено."),
        reply_markup=main_keyboard(statuses),
    )


@router.message(Command("skip"))
async def cmd_skip(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current == OnboardingStates.wait_announce.state:
        statuses = await finish_onboarding_skip_announce(message, state)
        await message.answer(
            "✅ Ок. Канал анонсов настроишь позже в ⚙️ → 📢",
            reply_markup=main_keyboard(statuses),
        )
        return
    if current == ActionStates.waiting_game_title.state:
        from src.bot.handlers.game_flow import apply_game_and_title

        await apply_game_and_title(message, state, title=None)
        await state.set_state(None)
        return
    if current == OnboardingStates.vk_web_token.state:
        from src.bot.handlers.onboarding import vk_web_token as onboarding_vk_web_token

        await onboarding_vk_web_token(message, state)
        return
    await message.answer("Используй /skip при запросе итога стрима или названия.")
