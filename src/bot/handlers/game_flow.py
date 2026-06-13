from __future__ import annotations

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from src.bot.keyboards import category_choices, category_confirm, title_skip_keyboard
from src.bot.platform_status import load_platform_statuses
from src.bot.reply_keyboards import main_keyboard
from src.db.database import get_session_factory
from src.db.models import PLATFORM_LABELS, Platform, PlatformConnection, User
from src.platforms.base import CategoryResult
from src.services.category_flow import cache_mapping, generic_for_platform, resolve_categories
from src.services.stream_ops import update_on_platforms, verify_platform_category, verify_platform_title
from src.services.titles import format_title_hint, prepare_title

router = Router()


def _serialize_choices(choices: dict[str, list[CategoryResult]]) -> dict[str, list[dict[str, str]]]:
    return {
        plat: [{"id": c.id, "name": c.name} for c in items]
        for plat, items in choices.items()
    }


def _deserialize_choices(raw: dict[str, list[dict[str, str]]]) -> dict[str, list[CategoryResult]]:
    return {
        plat: [CategoryResult(id=c["id"], name=c["name"]) for c in items]
        for plat, items in raw.items()
    }


def _all_categories_picked(data: dict) -> bool:
    waiting = set(data.get("platforms_waiting", []))
    pending = data.get("pending", {})
    return bool(pending) and waiting.issubset(pending.keys())


async def _safe_edit_text(message: Message, text: str, **kwargs) -> None:
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise


async def _apply_category_now(
    message: Message, user_id: int, platform: str, cat_id: str, cat_name: str
) -> str:
    """Сразу отправляет категорию на площадку и возвращает строку для ответа."""
    plat = Platform(platform)
    label = PLATFORM_LABELS[plat]
    factory = get_session_factory()
    async with factory() as session:
        errors = await update_on_platforms(
            session,
            user_id,
            platform_filter=plat,
            category_id=cat_id,
            title=None,
        )
        if errors:
            err = errors[0]
            if err.startswith(f"{label}:"):
                return f"❌ {err}"
            return f"❌ <b>{label}</b>: {err}"
        verify = await verify_platform_category(session, user_id, plat, cat_name)
        if verify:
            return f"✅ <b>{label}</b>: «{cat_name}»\n   <i>{verify}</i>"
        return f"✅ <b>{label}</b>: категория → «{cat_name}»"


async def _maybe_ask_title(message: Message, state: FSMContext) -> None:
    from src.bot.handlers.menu import ActionStates

    data = await state.get_data()
    if not _all_categories_picked(data):
        return
    await state.set_state(ActionStates.waiting_game_title)
    await message.answer(
        "Напиши название стрима или нажми «Пропустить»:\n\n"
        f"<i>Twitch: {format_title_hint(Platform.TWITCH)}</i>\n"
        f"<i>Kick: {format_title_hint(Platform.KICK)}</i>",
        parse_mode="HTML",
        reply_markup=title_skip_keyboard(),
    )


async def process_game_change(
    message: Message, state: FSMContext, game_query: str, *, platform_filter: Platform | None = None
) -> None:
    data = await state.get_data()
    target = data.get("target_platform", "all")
    pf = platform_filter or (None if target == "all" else Platform(target))

    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = r.scalar_one()
        r2 = await session.execute(
            select(PlatformConnection).where(
                PlatformConnection.user_id == user.id,
                PlatformConnection.enabled.is_(True),
            )
        )
        connections = list(r2.scalars())
        pick = await resolve_categories(session, user.id, connections, game_query, platform_filter=pf)

    pending: dict = data.get("pending", {})
    platforms_waiting: set[str] = set(data.get("platforms_waiting", []))
    for plat_value, err in pick.errors.items():
        await message.answer(
            f"⚠️ <b>{PLATFORM_LABELS[Platform(plat_value)]}</b>: {err}",
            parse_mode="HTML",
        )
    for conn in connections:
        if pf and conn.platform != pf.value:
            continue
        plat = Platform(conn.platform)
        if plat.value in pick.errors:
            continue
        label = PLATFORM_LABELS[plat]
        best = pick.pending.get(plat.value)
        if best and best.confidence >= 0.85 and plat.value not in pick.choices:
            platforms_waiting.add(plat.value)
            await message.answer(
                f"<b>{label}</b>: нашёл «{best.name}». Верно?",
                parse_mode="HTML",
                reply_markup=category_confirm(plat.value, best.id, best.name),
            )
        elif pick.choices.get(plat.value):
            platforms_waiting.add(plat.value)
            await message.answer(
                f"<b>{label}</b>: выбери категорию:",
                parse_mode="HTML",
                reply_markup=category_choices(plat.value, pick.choices[plat.value]),
            )
        elif best and best.confidence < 0.85:
            platforms_waiting.add(plat.value)
            await message.answer(
                f"<b>{label}</b>: похоже на «{best.name}». Верно?",
                parse_mode="HTML",
                reply_markup=category_confirm(plat.value, best.id, best.name),
            )
        elif best:
            pending[plat.value] = {"id": best.id, "name": best.name}
        else:
            platforms_waiting.add(plat.value)
            hint = ""
            if plat == Platform.VK:
                hint = (
                    "\n\n<i>VK: если игры нет в списке — «🔎 Уточнить» или выбери вручную.</i>"
                )
            await message.answer(
                f"<b>{label}</b>: не нашёл. Выбери категорию:{hint}",
                parse_mode="HTML",
                reply_markup=category_choices(plat.value, generic_for_platform(plat)),
            )

    await state.update_data(
        game_query=game_query,
        pending=pending,
        platforms_waiting=list(platforms_waiting),
        category_choices=_serialize_choices(pick.choices),
        categories_applied=list(data.get("categories_applied", [])),
        awaiting_title=False,
    )

    if _all_categories_picked(await state.get_data()):
        await _maybe_ask_title(message, state)


async def apply_game_and_title(message: Message, state: FSMContext, title: str | None) -> None:
    data = await state.get_data()
    pending = data.get("pending", {})
    target = data.get("target_platform", "all")
    pf = None if target == "all" else Platform(target)
    waiting = set(data.get("platforms_waiting", []))
    if waiting - pending.keys():
        missing = ", ".join(PLATFORM_LABELS[Platform(p)] for p in waiting - pending.keys())
        await message.answer(f"Сначала выбери категорию на: {missing}")
        return

    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = r.scalar_one()
        errors: list[str] = []
        updated: list[str] = []
        verify_lines: list[str] = []
        warnings: list[str] = []
        if title is not None:
            for plat_value in pending:
                if pf and plat_value != pf.value:
                    continue
                plat = Platform(plat_value)
                prep = prepare_title(title, plat)
                if prep.truncated and prep.note:
                    warnings.append(f"{PLATFORM_LABELS[plat]}: {prep.note}")
            if warnings:
                await message.answer("⚠️ " + "\n".join(warnings), parse_mode="HTML")
            for plat_value in pending:
                if pf and plat_value != pf.value:
                    continue
                plat = Platform(plat_value)
                plat_errors = await update_on_platforms(
                    session,
                    user.id,
                    platform_filter=plat,
                    title=title,
                    category_id=None,
                )
                if plat_errors:
                    errors.extend(plat_errors)
                else:
                    label = PLATFORM_LABELS[plat]
                    updated.append(label)
                    v = await verify_platform_title(session, user.id, plat, title)
                    if v:
                        verify_lines.append(f"<b>{label}</b>: {v}")

    statuses = await load_platform_statuses(message.from_user.id)
    await state.update_data(
        game_query=None,
        pending={},
        platforms_waiting=[],
        category_choices={},
        categories_applied=[],
        refine_platform=None,
        awaiting_title=False,
    )
    scope = "везде" if target == "all" else PLATFORM_LABELS[pf]
    if title is None:
        await message.answer(f"✅ Категории применены ({scope})", reply_markup=main_keyboard(statuses))
        return
    if errors:
        text = "Частично (название):\n" + "\n".join(errors)
        if updated:
            text += "\n\n✅ " + ", ".join(updated)
    else:
        text = f"✅ Название обновлено ({scope})"
        if updated:
            text += "\n" + ", ".join(updated)
    if verify_lines:
        text += "\n\n" + "\n".join(verify_lines)
    await message.answer(text, parse_mode="HTML", reply_markup=main_keyboard(statuses))


@router.callback_query(lambda c: c.data == "titleskip")
async def title_skip(cb: CallbackQuery, state: FSMContext) -> None:
    from src.bot.handlers.menu import ActionStates

    if await state.get_state() != ActionStates.waiting_game_title.state:
        await cb.answer("Уже не актуально")
        return
    await cb.answer("Пропущено")
    await cb.message.edit_reply_markup(reply_markup=None)
    await apply_game_and_title(cb.message, state, title=None)
    await state.set_state(None)


@router.callback_query(lambda c: c.data and c.data.startswith("catok:"))
async def cat_confirm_yes(cb: CallbackQuery, state: FSMContext) -> None:
    _, platform, cat_id = cb.data.split(":", 2)
    data = await state.get_data()
    pending = data.get("pending", {})
    name = cb.message.text.split("«")[1].split("»")[0] if "«" in (cb.message.text or "") else ""
    pending[platform] = {"id": cat_id, "name": name}
    applied = list(data.get("categories_applied", []))
    if platform not in applied:
        applied.append(platform)
    await state.update_data(pending=pending, categories_applied=applied)

    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == cb.from_user.id))
        user = r.scalar_one()
        await cache_mapping(
            session, user.id, data.get("game_query", ""), Platform(platform),
            CategoryResult(id=cat_id, name=name),
        )

    result = await _apply_category_now(cb.message, user.id, platform, cat_id, name)
    await cb.answer("Ок")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(result, parse_mode="HTML")
    await _maybe_ask_title(cb.message, state)


@router.callback_query(lambda c: c.data and c.data.startswith("catno:"))
async def cat_confirm_no(cb: CallbackQuery, state: FSMContext) -> None:
    platform = cb.data.split(":")[1]
    plat = Platform(platform)
    data = await state.get_data()
    pending = data.get("pending", {})
    pending.pop(platform, None)
    await state.update_data(pending=pending)
    choices_map = _deserialize_choices(data.get("category_choices", {}))
    choices = choices_map.get(platform, [])
    if choices:
        await _safe_edit_text(
            cb.message,
            f"<b>{PLATFORM_LABELS[plat]}</b> — выбери из результатов:",
            parse_mode="HTML",
            reply_markup=category_choices(platform, choices),
        )
    else:
        await state.update_data(refine_platform=platform)
        from src.bot.handlers.menu import ActionStates

        await state.set_state(ActionStates.waiting_game_refine)
        await _safe_edit_text(
            cb.message,
            f"<b>{PLATFORM_LABELS[plat]}</b> — напиши 3+ буквы игры для поиска:",
            parse_mode="HTML",
        )
    await cb.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("catpick:"))
async def cat_pick(cb: CallbackQuery, state: FSMContext) -> None:
    _, platform, cat_id = cb.data.split(":", 2)
    name = cat_id
    for row in cb.message.reply_markup.inline_keyboard:
        for btn in row:
            if btn.callback_data == cb.data:
                name = btn.text
    data = await state.get_data()
    pending = data.get("pending", {})
    pending[platform] = {"id": cat_id, "name": name}
    applied = list(data.get("categories_applied", []))
    if platform not in applied:
        applied.append(platform)
    await state.update_data(pending=pending, categories_applied=applied)

    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == cb.from_user.id))
        user = r.scalar_one()
        await cache_mapping(
            session, user.id, data.get("game_query", ""), Platform(platform),
            CategoryResult(id=cat_id, name=name),
        )

    result = await _apply_category_now(cb.message, user.id, platform, cat_id, name)
    await cb.answer(f"Выбрано: {name}")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(result, parse_mode="HTML")
    await _maybe_ask_title(cb.message, state)


@router.callback_query(lambda c: c.data and c.data.startswith("catother:"))
async def cat_other(cb: CallbackQuery) -> None:
    platform = cb.data.split(":")[1]
    plat = Platform(platform)
    await _safe_edit_text(
        cb.message,
        f"<b>{PLATFORM_LABELS[plat]}</b> — общие категории:",
        parse_mode="HTML",
        reply_markup=category_choices(
            platform, generic_for_platform(plat), show_other=False, show_refine=True
        ),
    )
    await cb.answer("Выбери категорию")


@router.callback_query(lambda c: c.data and c.data.startswith("catrefine:"))
async def cat_refine(cb: CallbackQuery, state: FSMContext) -> None:
    platform = cb.data.split(":")[1]
    plat = Platform(platform)
    await state.update_data(refine_platform=platform)
    from src.bot.handlers.menu import ActionStates

    await state.set_state(ActionStates.waiting_game_refine)
    await _safe_edit_text(
        cb.message,
        f"<b>{PLATFORM_LABELS[plat]}</b> — напиши часть названия игры (3+ буквы):",
        parse_mode="HTML",
    )
    await cb.answer()


async def process_game_refine(message: Message, state: FSMContext, query: str) -> None:
    data = await state.get_data()
    platform = data.get("refine_platform")
    if not platform:
        await message.answer("Сначала выбери площадку.")
        return
    plat = Platform(platform)
    await process_game_change(message, state, query, platform_filter=plat)
    await state.set_state(None)
