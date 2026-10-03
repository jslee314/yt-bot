"""제목 확인/수정 콜백 핸들러."""

import json
import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import LOCAL_YT_PRODUCTION_DIR
from handlers.common import auth_check, ssh_connect_error_reply, reject_bad_id, valid_video_id
from services.runner import runner as ssh
from services.state import save_decision

logger = logging.getLogger(__name__)


@auth_check
async def title_change_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """제목 변경 버튼 콜백 — 새 제목 입력 대기."""
    query = update.callback_query
    await query.answer()

    video_id = query.data.split(":")[1]
    if await reject_bad_id(query, video_id):
        return
    context.user_data["waiting_for"] = "title"
    context.user_data["pending_video_id"] = video_id

    # 현재 제목 표시
    try:
        metadata_path = f"{LOCAL_YT_PRODUCTION_DIR}/runs/{video_id}_script/metadata.json"
        metadata_str = ssh.read_file(metadata_path)
        metadata = json.loads(metadata_str)
        current_title = metadata.get("title", "")
    except Exception:
        current_title = "(확인 불가)"

    await query.edit_message_text(
        f"\uc0c8 \uc81c\ubaa9\uc744 \uc785\ub825\ud558\uc138\uc694.\n\ud604\uc7ac: {current_title}"
    )


async def handle_title_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """새 제목 텍스트 입력 처리."""
    video_id = context.user_data.get("pending_video_id")
    if not video_id:
        return
    if not valid_video_id(video_id):
        await update.message.reply_text("⚠️ 잘못된 영상 ID 형식입니다.")
        return

    new_title = update.message.text.strip()
    if not new_title:
        await update.message.reply_text("\uc81c\ubaa9\uc744 \uc785\ub825\ud574\uc8fc\uc138\uc694.")
        return

    try:
        metadata_path = f"{LOCAL_YT_PRODUCTION_DIR}/runs/{video_id}_script/metadata.json"
        metadata_str = ssh.read_file(metadata_path)
        metadata = json.loads(metadata_str)
        metadata["title"] = new_title
        ssh.write_file(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2))
    except Exception:
        await ssh_connect_error_reply(update)
        return

    save_decision(video_id, "title", new_title)

    context.user_data.pop("waiting_for", None)
    context.user_data.pop("pending_video_id", None)

    await update.message.reply_text(f"\u2705 \uc81c\ubaa9 \ubcc0\uacbd \uc644\ub8cc: {new_title}")
