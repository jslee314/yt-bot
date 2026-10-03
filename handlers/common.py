"""공통 유틸 — 인증 체크, 에러 핸들링, 텍스트 입력 라우팅."""

import functools
import re
import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import CHAT_ID
from services.validation import valid_video_id

logger = logging.getLogger(__name__)


def auth_check(func):
    """chat_id 기반 인증 데코레이터. 허가되지 않은 사용자는 무시."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat_id = update.effective_chat.id if update.effective_chat else None
        user = update.effective_user
        # chat_id만 보면, TELEGRAM_CHAT_ID에 그룹 ID(음수)가 들어갔을 때
        # 그 그룹의 모든 구성원이 조작 명령을 쓸 수 있게 된다.
        # deploy/install_local.sh의 ID 추출 regex가 음수도 잡으므로 실수 가능성이 있다.
        if chat_id != CHAT_ID or not user or user.id != CHAT_ID:
            logger.debug("Unauthorized access from chat_id=%s user=%s",
                         chat_id, user.id if user else None)
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


# ── video_id 검증 ────────────────────────────────────────────
# callback_data는 봇이 만든 버튼이라도 신뢰할 수 없다 — 아무 MTProto 클라이언트나
# 임의의 64바이트를 보낼 수 있다. 이 값이 shell=True 명령과 파일 경로에 그대로
# 들어가므로, 쓰기 전에 ID 형식을 강제한다. 형식은 config.CHANNELS의 id_re와 같다.


async def reject_bad_id(query, video_id: str) -> bool:
    """형식이 아니면 거부하고 True를 반환한다 (호출부는 즉시 return)."""
    if valid_video_id(video_id):
        return False
    logger.warning("Rejected malformed video_id=%r", video_id)
    await query.edit_message_text("\u26a0\ufe0f 잘못된 영상 ID 형식입니다.")
    return True
