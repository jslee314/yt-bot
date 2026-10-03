"""
파이프라인에서 사용하는 Telegram 알림 발송.
yt-bot 서버 없이도 동작 (Bot API 직접 호출).

사용법 (yt-script/yt-production에서):
    from notify.send import notify_script_complete, notify_production_complete
"""

import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# 다른 프로젝트(yt-script 등)에서 import해도 토큰을 찾을 수 있도록 명시 로드.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_message(text: str, reply_markup: dict = None):
    """텍스트 메시지 전송"""
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(f"{API_BASE}/sendMessage", json=payload)


def send_photo(photo_path: str, caption: str = "", reply_markup: dict = None):
    """이미지 + 캡션 전송"""
    payload = {"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    with open(photo_path, "rb") as f:
        requests.post(f"{API_BASE}/sendPhoto", data=payload, files={"photo": f})


def notify_script_complete(video_id: str, metadata: dict, output_dir: str):
    """
    yt-script 완료 알림 (알림 1)

    yt-script/nodes/save_outputs.py 마지막에 호출.
    """
    title = metadata.get("title", "제목 없음")
    total_chars = metadata.get("total_chars", 0)
    chapters = metadata.get("chapters_count", 0)
    shorts_count = metadata.get("shorts_count", 0)

    # 훅 후보
    hook_candidates = metadata.get("hook_candidates", [])
    hook_text = "\n".join(f"{i+1}\ufe0f\u20e3 {h}" for i, h in enumerate(hook_candidates))

    # 썸네일 문구 후보
    thumb = metadata.get("thumbnail", {})
    thumb_candidates = thumb.get("text_candidates", [])
    thumb_text = "\n".join(
        f'{i+1}\ufe0f\u20e3 {t["line1"]} / {t["line2"]}'
        for i, t in enumerate(thumb_candidates)
    )

    text = (
        f"\U0001f4dd <b>\ub300\ubcf8 \uc644\uc131 \u2014 {video_id}</b>\n\n"
        f"\uc81c\ubaa9: {title}\n"
        f"\uae00\uc790\uc218: {total_chars:,}\uc790 | \ucc55\ud130: {chapters}\uac1c | \uc219\ud3fc: {shorts_count}\uac1c\n\n"
        f"\u2501\u2501\u2501 \ud6c5 (\ud604\uc7ac: #1 \uc790\ub3d9\uc120\ud0dd) \u2501\u2501\u2501\n{hook_text}\n\n"
        f"\u2501\u2501\u2501 \uc378\ub124\uc77c \ubb38\uad6c (\ud604\uc7ac: #1 \uc790\ub3d9\uc120\ud0dd) \u2501\u2501\u2501\n{thumb_text}\n\n"
        f"\u2705 \uc218\uc815 \uc5c6\uc73c\uba74 \ubb34\uc2dc\ud558\uc138\uc694. \uc774\ubbf8 1\ubc88\uc73c\ub85c \uc9c4\ud589\ub429\ub2c8\ub2e4."
    )

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "\ud6c5 \ubcc0\uacbd", "callback_data": f"hook_change:{video_id}"},
                {"text": "\uc378\ub124\uc77c \ubb38\uad6c \ubcc0\uacbd", "callback_data": f"thumb_change:{video_id}"},
                {"text": "\uc81c\ubaa9 \ubcc0\uacbd", "callback_data": f"title_change:{video_id}"},
            ]
        ]
    }

    send_message(text, reply_markup)


def notify_production_complete(video_id: str, metadata: dict, run_dir: str):
    """
    yt-production 완료 알림 (알림 2)

    yt-production/make_all.py 마지막에 호출.
    """
    title = metadata.get("title", "제목 없음")
    duration = metadata.get("duration", "")
    cuts = metadata.get("cuts_count", 0)
    shorts_count = metadata.get("shorts_count", 0)

    text = (
        f"\U0001f3ac <b>\uc601\uc0c1 \uc644\uc131 \u2014 {video_id}</b>\n\n"
        f"\uc81c\ubaa9: {title}\n"
    )
    if duration:
        text += f"\ub871\ud3fc: {duration} | {cuts}\ucef7 | 1920x1080\n"
    if shorts_count:
        text += f"\uc219\ud3fc: {shorts_count}\uac1c \uc644\uc131\n"
    text += f"\n\uc5c5\ub85c\ub4dc \uc900\ube44 \uc644\ub8cc. \uc544\ub798 \ubc84\ud2bc\uc73c\ub85c \uc5c5\ub85c\ub4dc\ud558\uc138\uc694."

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "\U0001f680 \uc9c0\uae08 \uc5c5\ub85c\ub4dc", "callback_data": f"upload_now:{video_id}"},
                {"text": "\u23f0 \uc608\uc57d \uc5c5\ub85c\ub4dc", "callback_data": f"upload_schedule:{video_id}"},
            ],
            [
                {"text": "\uc378\ub124\uc77c \ubcc0\uacbd", "callback_data": f"thumb_change_prod:{video_id}"},
            ],
        ]
    }

    # 썸네일 이미지 전송
    thumb_path = os.path.join(run_dir, "thumbnail", "thumbnail.png")
    if os.path.exists(thumb_path):
        send_photo(thumb_path, text, reply_markup)
    else:
        send_message(text, reply_markup)
