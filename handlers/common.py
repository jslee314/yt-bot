"""공통 유틸 — 인증 체크, 에러 핸들링, 텍스트 입력 라우팅."""

import functools
import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import CHAT_ID

logger = logging.getLogger(__name__)


def auth_check(func):
    """chat_id 기반 인증 데코레이터. 허가되지 않은 사용자는 무시."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id != CHAT_ID:
            logger.warning("Unauthorized access from chat_id=%s", chat_id)
            return
        return await func(update, context, *args, **kwargs)

    return wrapper


async def ssh_error_reply(update: Update, err: str, action: str):
    """SSH 명령 실패 시 에러 메시지 전송."""
    text = (
        f"\u26a0\ufe0f {action} \uc2e4\ud328\n\n"
        f"<pre>{err[:1000]}</pre>\n\n"
        "\uc218\ub3d9 \ud655\uc778\uc774 \ud544\uc694\ud569\ub2c8\ub2e4."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(text, parse_mode="HTML")


async def ssh_connect_error_reply(update: Update):
    """SSH 접속 실패 시 에러 메시지."""
    text = "\u26a0\ufe0f \ub85c\uceec PC\uc5d0 \uc811\uc18d\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4. PC\uac00 \ucf1c\uc838 \uc788\ub294\uc9c0 \ud655\uc778\ud558\uc138\uc694."
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    elif update.message:
        await update.message.reply_text(text)
