"""yt-bot — Telegram 봇 메인 진입점 (polling 방식)."""

import logging

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from config import BOT_TOKEN, CHAT_ID
from handlers import script_complete, production_complete
from handlers.common import auth_check
from handlers.thumbnail import handle_thumb_direct_input
from handlers.title import handle_title_input
from handlers.upload import handle_schedule_input
from services.state import init_db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


@auth_check
async def text_input_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """텍스트 메시지 라우터 — user_data 상태에 따라 적절한 핸들러로 분기."""
    waiting_for = context.user_data.get("waiting_for")

    if waiting_for == "title":
        await handle_title_input(update, context)
    elif waiting_for == "thumbnail":
        await handle_thumb_direct_input(update, context)
    elif waiting_for == "schedule":
        await handle_schedule_input(update, context)


def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # 알림 1 관련 핸들러 (훅, 썸네일, 제목)
    script_complete.register(app)

    # 알림 2 관련 핸들러 (업로드, 예약, 썸네일 변경)
    production_complete.register(app)

    # 텍스트 입력 라우터 (제목, 썸네일 직접입력, 예약시간)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_router))

    logger.info("yt-bot started (chat_id=%s)", CHAT_ID)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
