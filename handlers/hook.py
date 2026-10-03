"""훅 선택/변경 콜백 핸들러."""

import json
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import LOCAL_YT_PRODUCTION_DIR, LOCAL_YT_SCRIPT_DIR, PYTHON_BIN
from handlers.common import auth_check, ssh_connect_error_reply, ssh_error_reply, reject_bad_id
from services.runner import runner as ssh
from services.state import save_decision

logger = logging.getLogger(__name__)


@auth_check
async def hook_change_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """훅 변경 버튼 콜백 — 훅 번호 선택 버튼 표시."""
    query = update.callback_query
    await query.answer()

    video_id = query.data.split(":")[1]
    if await reject_bad_id(query, video_id):
        return

    try:
        metadata_path = f"{LOCAL_YT_PRODUCTION_DIR}/runs/{video_id}_script/metadata.json"
        metadata_str = ssh.read_file(metadata_path)
        metadata = json.loads(metadata_str)
    except Exception:
        await ssh_connect_error_reply(update)
        return

    hook_candidates = metadata.get("hook_candidates", [])
    if not hook_candidates:
        await query.edit_message_text("\u26a0\ufe0f \ud6c5 \ud6c4\ubcf4\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.")
        return

    buttons = []
    row = []
    for i, h in enumerate(hook_candidates):
        row.append(
            InlineKeyboardButton(
                str(i + 1), callback_data=f"hook_select:{video_id}:{i}"
            )
        )
    buttons.append(row)

    # 후보 텍스트 표시
    hook_text = "\n".join(f"{i+1}\ufe0f\u20e3 {h}" for i, h in enumerate(hook_candidates))
    await query.edit_message_text(
        f"\ud6c5 \ubc88\ud638\ub97c \uc120\ud0dd\ud558\uc138\uc694:\n\n{hook_text}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@auth_check
async def hook_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """훅 번호 선택 콜백 — SSH로 rehook 실행."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    video_id = parts[1]
    if await reject_bad_id(query, video_id):
        return
    index = int(parts[2])

    await query.edit_message_text(f"\u2705 \ud6c5 #{index + 1} \uc120\ud0dd. \uc7ac\uc0dd\uc131 \uc911...")

    try:
        cmd = (
            f"cd {LOCAL_YT_SCRIPT_DIR} && "
            f"{PYTHON_BIN} run.py rehook {video_id} --hook-index {index}"
        )
        out, err = ssh.execute(cmd)
    except Exception:
        await ssh_connect_error_reply(update)
        return

    if err and "error" in err.lower():
        await ssh_error_reply(update, err, "\ud6c5 \ubcc0\uacbd")
        return

    save_decision(video_id, "hook", str(index))

    await query.edit_message_text(
        f"\u2705 \ud6c5 #{index + 1} \ubcc0\uacbd \uc644\ub8cc. yt-production \uc7ac\uc2e4\ud589\uc774 \ud544\uc694\ud569\ub2c8\ub2e4."
    )
