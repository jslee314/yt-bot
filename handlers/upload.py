"""업로드 트리거 + 예약 콜백 핸들러."""

import logging
import re
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import LOCAL_YT_UPLOAD_DIR, PYTHON_BIN
from handlers.common import auth_check, ssh_connect_error_reply, ssh_error_reply, reject_bad_id, valid_video_id
from services.runner import runner as ssh
from services.state import save_decision

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


@auth_check
async def upload_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """즉시 업로드 콜백."""
    query = update.callback_query
    await query.answer()

    video_id = query.data.split(":")[1]
    if await reject_bad_id(query, video_id):
        return
    await query.edit_message_text("\U0001f4e4 \uc5c5\ub85c\ub4dc \uc2dc\uc791...")

    try:
        cmd = f"cd {LOCAL_YT_UPLOAD_DIR} && {PYTHON_BIN} run.py upload {video_id}"
        out, err = ssh.execute(cmd)
    except Exception:
        await ssh_connect_error_reply(update)
        return

    if err and "error" in err.lower():
        await ssh_error_reply(update, err, "\uc5c5\ub85c\ub4dc")
        return

    save_decision(video_id, "uploaded", "now")

    # 결과에서 URL 추출 시도
    result_text = f"\u2705 \uc5c5\ub85c\ub4dc \uc644\ub8cc!"
    if out:
        result_text += f"\n\n{out[:500]}"

    await query.edit_message_text(result_text)


@auth_check
async def upload_schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """예약 업로드 콜백 — 노출 시각 입력 대기."""
    query = update.callback_query
    await query.answer()

    video_id = query.data.split(":")[1]
    if await reject_bad_id(query, video_id):
        return
    context.user_data["waiting_for"] = "schedule"
    context.user_data["pending_video_id"] = video_id

    await query.edit_message_text(
        "\ub178\ucd9c \uc2dc\uac01\uc744 \uc785\ub825\ud558\uc138\uc694\n"
        "(\uc608: \ub0b4\uc77c 18\uc2dc, 3/15 20:00, 2026-03-15 18:00)"
    )


async def handle_schedule_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """노출 시각 텍스트 입력 처리."""
    video_id = context.user_data.get("pending_video_id")
    if not video_id:
        return
    if not valid_video_id(video_id):
        await update.message.reply_text("⚠️ 잘못된 영상 ID 형식입니다.")
        return

    text = update.message.text.strip()
    dt = _parse_datetime(text)
    if dt is None:
        await update.message.reply_text(
            "\u26a0\ufe0f \uc2dc\uac04\uc744 \uc778\uc2dd\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.\n"
            "\uc608: \ub0b4\uc77c 18\uc2dc, 3/15 20:00"
        )
        return

    dt_str = dt.strftime("%Y-%m-%d %H:%M KST")
    iso_str = dt.isoformat()

    context.user_data["schedule_dt"] = iso_str

    buttons = [
        [
            InlineKeyboardButton("\ud655\uc778", callback_data=f"schedule_confirm:{video_id}"),
            InlineKeyboardButton("\ucde8\uc18c", callback_data=f"schedule_cancel:{video_id}"),
        ]
    ]
    await update.message.reply_text(
        f"\U0001f4c5 {dt_str} \uc608\uc57d \ud655\uc778\n"
        f"private\uc73c\ub85c \uc989\uc2dc \uc5c5\ub85c\ub4dc + \uc608\uc57d \uacf5\uac1c\ub429\ub2c8\ub2e4.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@auth_check
async def schedule_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """예약 확인 콜백."""
    query = update.callback_query
    await query.answer()

    video_id = query.data.split(":")[1]
    if await reject_bad_id(query, video_id):
        return
    iso_str = context.user_data.get("schedule_dt")
    if not iso_str:
        await query.edit_message_text("\u26a0\ufe0f \uc608\uc57d \uc815\ubcf4\uac00 \uc5c6\uc2b5\ub2c8\ub2e4. \ub2e4\uc2dc \uc2dc\ub3c4\ud574\uc8fc\uc138\uc694.")
        return

    await query.edit_message_text("\U0001f4e4 \uc5c5\ub85c\ub4dc \uc911...")

    try:
        cmd = (
            f"cd {LOCAL_YT_UPLOAD_DIR} && "
            f'{PYTHON_BIN} run.py upload {video_id} --publish-at "{iso_str}"'
        )
        out, err = ssh.execute(cmd)
    except Exception:
        await ssh_connect_error_reply(update)
        return

    if err and "error" in err.lower():
        await ssh_error_reply(update, err, "\uc608\uc57d \uc5c5\ub85c\ub4dc")
        return

    save_decision(video_id, "publish_at", iso_str)

    context.user_data.pop("waiting_for", None)
    context.user_data.pop("pending_video_id", None)
    context.user_data.pop("schedule_dt", None)

    result_text = f"\u2705 \uc608\uc57d \uc5c5\ub85c\ub4dc \uc644\ub8cc! {iso_str} \uacf5\uac1c \uc608\uc815"
    if out:
        result_text += f"\n\n{out[:500]}"
    await query.edit_message_text(result_text)


@auth_check
async def schedule_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """예약 취소 콜백."""
    query = update.callback_query
    await query.answer()

    context.user_data.pop("waiting_for", None)
    context.user_data.pop("pending_video_id", None)
    context.user_data.pop("schedule_dt", None)

    await query.edit_message_text("\u274c \uc608\uc57d\uc774 \ucde8\uc18c\ub418\uc5c8\uc2b5\ub2c8\ub2e4.")


def _parse_datetime(text: str) -> datetime | None:
    """한국어 시간 표현 파싱 → KST datetime 반환."""
    now = datetime.now(KST)

    # "내일 18시" / "내일 18:00"
    m = re.match(r"내일\s+(\d{1,2})(?::(\d{2}))?\s*시?", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        return (now + timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)

    # "모레 18시"
    m = re.match(r"모레\s+(\d{1,2})(?::(\d{2}))?\s*시?", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        return (now + timedelta(days=2)).replace(hour=h, minute=mi, second=0, microsecond=0)

    # "3/15 20:00" / "3/15 20시"
    m = re.match(r"(\d{1,2})/(\d{1,2})\s+(\d{1,2})(?::(\d{2}))?\s*시?", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        h, mi = int(m.group(3)), int(m.group(4) or 0)
        year = now.year
        dt = datetime(year, month, day, h, mi, tzinfo=KST)
        if dt < now:
            dt = dt.replace(year=year + 1)
        return dt

    # "2026-03-15 18:00"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", text)
    if m:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)),
            tzinfo=KST,
        )

    # "오늘 18시"
    m = re.match(r"오늘\s+(\d{1,2})(?::(\d{2}))?\s*시?", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        return now.replace(hour=h, minute=mi, second=0, microsecond=0)

    return None
