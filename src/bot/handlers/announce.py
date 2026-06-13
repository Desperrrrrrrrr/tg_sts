from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy import select

from src.bot.platform_status import load_platform_statuses
from src.bot.reply_keyboards import main_keyboard
from src.db.database import get_session_factory
from src.db.models import AnnounceTarget, User

router = Router()


@router.message(F.forward_from_chat)
async def set_announce_chat(message: Message) -> None:
    chat = message.forward_from_chat
    if not chat:
        return
    factory = get_session_factory()
    async with factory() as session:
        r = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = r.scalar_one_or_none()
        if not user:
            return
        r2 = await session.execute(select(AnnounceTarget).where(AnnounceTarget.user_id == user.id))
        target = r2.scalar_one_or_none()
        if target:
            target.chat_id = chat.id
            target.chat_title = chat.title
        else:
            session.add(AnnounceTarget(user_id=user.id, chat_id=chat.id, chat_title=chat.title))
        await session.commit()
    statuses = await load_platform_statuses(message.from_user.id)
    await message.answer(
        f"✅ Анонсы будут публиковаться в: {chat.title or chat.id}",
        reply_markup=main_keyboard(statuses),
    )
