"""yt-bot — Telegram 봇 메인 진입점 (롱폴링).

파이프라인과 같은 맥에서 돈다. 롱폴링이라 텔레그램으로 나가는 연결만 쓰므로
포트 개방·DDNS·클라우드 VM이 필요 없다.
"""

import asyncio
import logging

from telegram import BotCommand, Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

import config
from config import BOT_TOKEN, CHAT_ID
from handlers import commands, production_complete, script_complete
from handlers.common import auth_check
from handlers.thumbnail import handle_thumb_direct_input
from handlers.title import handle_title_input
from handlers.upload import handle_schedule_input
from services.state import init_db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
# httpx는 요청 URL을 통째로 INFO로 찍는데, 텔레그램 API URL에는 봇 토큰이
# 그대로 들어 있다. 로그 파일에 토큰이 평문으로 쌓이는 걸 막는다.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

MENU = [
    BotCommand("status", "파이프라인 상태"),
    BotCommand("queue", "남은 작업 목록"),
    BotCommand("run", "지금 실행"),
    BotCommand("log", "최근 로그"),
    BotCommand("stop", "실행 중단"),
    BotCommand("help", "도움말"),
]


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
    else:
        await update.message.reply_text("명령은 /help 를 보세요.")


async def _post_init(app: Application):
    """폰의 명령 메뉴(/ 버튼)에 명령 목록을 등록."""
    await app.bot.set_my_commands(MENU)
    logger.info("command menu registered")


def main():
    config.validate()
    init_db()

    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    # 슬래시 명령 (상태 확인 / 실행 / 로그)
    commands.register(app)

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
