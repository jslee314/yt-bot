"""썸네일 문구 선택/변경 콜백 핸들러."""

import json
import logging
import os
import tempfile

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import LOCAL_YT_PRODUCTION_DIR, PYTHON_BIN
from handlers.common import auth_check, ssh_connect_error_reply, ssh_error_reply, reject_bad_id, valid_video_id
from services.runner import runner as ssh
from services.state import save_decision

logger = logging.getLogger(__name__)


async def _show_thumb_candidates(update: Update, video_id: str, context: ContextTypes.DEFAULT_TYPE):
    """썸네일 후보 목록 표시 (알림1, 알림2 공통)."""
    query = update.callback_query

    try:
        metadata_path = f"{LOCAL_YT_PRODUCTION_DIR}/runs/{video_id}_script/metadata.json"
        metadata_str = ssh.read_file(metadata_path)
        metadata = json.loads(metadata_str)
    except Exception:
        await ssh_connect_error_reply(update)
        return

    candidates = metadata.get("thumbnail", {}).get("text_candidates", [])
    if not candidates:
        await query.edit_message_text("\u26a0\ufe0f \uc378\ub124\uc77c \ubb38\uad6c \ud6c4\ubcf4\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.")
        return

    buttons = []
    for i, c in enumerate(candidates):
        buttons.append([
            InlineKeyboardButton(
                f'{i + 1}. {c["line1"]} / {c["line2"]}',
                callback_data=f"thumb_select:{video_id}:{i}",
            )
        ])

    context.user_data["waiting_for"] = "thumbnail"
    context.user_data["pending_video_id"] = video_id

    await query.edit_message_text(
        "\uc378\ub124\uc77c \ubb38\uad6c\ub97c \uc120\ud0dd\ud558\uc138\uc694.\n\uc9c1\uc811 \uc785\ub825: line1 / line2 \ud615\uc2dd\uc73c\ub85c \uba54\uc2dc\uc9c0 \uc804\uc1a1",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@auth_check
async def thumb_change_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """썸네일 문구 변경 버튼 콜백 (알림 1)."""
    query = update.callback_query
    await query.answer()
    video_id = query.data.split(":")[1]
    if await reject_bad_id(query, video_id):
        return
    await _show_thumb_candidates(update, video_id, context)


@auth_check
async def thumb_change_prod_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """썸네일 변경 버튼 콜백 (알림 2) — 문구만/전체 재생성 선택."""
    query = update.callback_query
    await query.answer()
    video_id = query.data.split(":")[1]
    if await reject_bad_id(query, video_id):
        return

    buttons = [
        [
            InlineKeyboardButton(
                "\ubb38\uad6c\ub9cc \ubcc0\uacbd", callback_data=f"thumb_change:{video_id}"
            ),
            InlineKeyboardButton(
                "\uc774\ubbf8\uc9c0+\ubb38\uad6c \uc804\uccb4 \uc7ac\uc0dd\uc131",
                callback_data=f"thumb_full_regen:{video_id}",
            ),
        ]
    ]
    await query.edit_message_text(
        "\ubcc0\uacbd \ubc29\ubc95\uc744 \uc120\ud0dd\ud558\uc138\uc694",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@auth_check
async def thumb_full_regen_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """이미지+문구 전체 재생성 콜백."""
    query = update.callback_query
    await query.answer()
    video_id = query.data.split(":")[1]
    if await reject_bad_id(query, video_id):
        return

    await query.edit_message_text("\U0001f504 Whisk AI \uc774\ubbf8\uc9c0 + Pillow \ud569\uc131 \uc7ac\uc2e4\ud589 \uc911...")

    try:
        cmd = (
            f"cd {LOCAL_YT_PRODUCTION_DIR} && "
            f"{PYTHON_BIN} -m thumbnail.generator --run-dir runs/{video_id}_script/ && "
            f"{PYTHON_BIN} -m thumbnail.composer --run-dir runs/{video_id}_script/"
        )
        out, err = ssh.execute(cmd)
    except Exception:
        await ssh_connect_error_reply(update)
        return

    if err and "error" in err.lower():
        await ssh_error_reply(update, err, "\uc378\ub124\uc77c \uc804\uccb4 \uc7ac\uc0dd\uc131")
        return

    save_decision(video_id, "thumbnail_full_regen", "true")

    # 새 썸네일 전송
    await _send_new_thumbnail(update, context, video_id)


@auth_check
async def thumb_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """번호 선택 콜백 — SSH로 Pillow 합성 재실행."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    video_id = parts[1]
    if await reject_bad_id(query, video_id):
        return
    index = int(parts[2])

    try:
        metadata_path = f"{LOCAL_YT_PRODUCTION_DIR}/runs/{video_id}_script/metadata.json"
        metadata_str = ssh.read_file(metadata_path)
        metadata = json.loads(metadata_str)
    except Exception:
        await ssh_connect_error_reply(update)
        return

    selected = metadata["thumbnail"]["text_candidates"][index]
    await query.edit_message_text(f"\u2705 \uc378\ub124\uc77c \ubb38\uad6c #{index + 1} \uc120\ud0dd. \uc7ac\uc0dd\uc131 \uc911...")

    await _regenerate_thumbnail(update, context, video_id, selected)

    context.user_data.pop("waiting_for", None)
    context.user_data.pop("pending_video_id", None)


async def handle_thumb_direct_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """직접 입력 처리 (line1 / line2 형식)."""
    video_id = context.user_data.get("pending_video_id")
    if not video_id:
        return
    if not valid_video_id(video_id):
        await update.message.reply_text("⚠️ 잘못된 영상 ID 형식입니다.")
        return

    text = update.message.text
    if "/" not in text:
        await update.message.reply_text("\ud615\uc2dd: line1 / line2")
        return

    parts = text.split("/", 1)
    selected = {"line1": parts[0].strip(), "line2": parts[1].strip()}

    await update.message.reply_text(f"\u2705 \uc9c1\uc811 \uc785\ub825 \ud655\uc778. \uc7ac\uc0dd\uc131 \uc911...")

    await _regenerate_thumbnail(update, context, video_id, selected)

    context.user_data.pop("waiting_for", None)
    context.user_data.pop("pending_video_id", None)


async def _regenerate_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE, video_id: str, selected: dict):
    """선택된 문구로 썸네일 재생성."""
    try:
        # selected_text.json 저장
        selected_path = f"{LOCAL_YT_PRODUCTION_DIR}/runs/{video_id}_script/thumbnail/selected_text.json"
        ssh.write_file(selected_path, json.dumps(selected, ensure_ascii=False))

        # Pillow 합성 재실행
        cmd = (
            f"cd {LOCAL_YT_PRODUCTION_DIR} && "
            f"{PYTHON_BIN} -m thumbnail.composer --run-dir runs/{video_id}_script/"
        )
        out, err = ssh.execute(cmd)
    except Exception:
        await ssh_connect_error_reply(update)
        return

    if err and "error" in err.lower():
        await ssh_error_reply(update, err, "\uc378\ub124\uc77c \uc7ac\uc0dd\uc131")
        return

    save_decision(video_id, "thumbnail_text", json.dumps(selected, ensure_ascii=False))

    await _send_new_thumbnail(update, context, video_id)


async def _send_new_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE, video_id: str):
    """새 썸네일 이미지 다운로드 후 전송."""
    chat_id = update.effective_chat.id
    remote_thumb = f"{LOCAL_YT_PRODUCTION_DIR}/runs/{video_id}_script/thumbnail/thumbnail.png"
    local_tmp = os.path.join(tempfile.gettempdir(), f"{video_id}_thumb.png")

    try:
        ssh.download_file(remote_thumb, local_tmp)
    except Exception:
        if update.callback_query:
            await update.callback_query.edit_message_text("\u2705 \uc378\ub124\uc77c \uc7ac\uc0dd\uc131 \uc644\ub8cc (\uc774\ubbf8\uc9c0 \ub2e4\uc6b4\ub85c\ub4dc \uc2e4\ud328)")
        return

    with open(local_tmp, "rb") as f:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=f,
            caption="\u2705 \uc378\ub124\uc77c \uc7ac\uc0dd\uc131 \uc644\ub8cc",
        )

    os.remove(local_tmp)
