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
from handlers import help as help_cmd
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
    BotCommand("schedule", "공개 일정"),
    BotCommand("stop", "실행 중단"),
    BotCommand("stuck", "공개 안 된 영상 점검"),
    BotCommand("link", "숏폼→롱폼 관련 동영상 걸기"),
    BotCommand("help", "사용법 (/help 주제 · /help pin)"),
]

# 봇 프로필의 "이 봇은 무엇을 할 수 있나요?" — 채팅을 처음 열 때 보인다. (설명 512자, 짧은 설명 120자 제한)
SHORT_DESCRIPTION = "괜찮아연구소·今日もこんなふうに 유튜브 자동화 — 상태 확인·실행·알림·숏폼 링크"
DESCRIPTION = (
    "유튜브 자동화 파이프라인을 폰에서 봅니다.\n"
    "/status 상태 · /run 실행 · /log 로그 · /stuck 미공개 점검 · /link 숏폼→롱폼 링크\n"
    "채널: ko 괜찮아연구소(기본) · ja 今日もこんなふうに — 명령 뒤에 채널을 붙입니다.\n"
    "영상이 완성되거나 실패하면 알림이 자동으로 옵니다. 사용법: /help"
)


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
    """폰의 명령 메뉴(/ 버튼)와 봇 프로필 설명을 등록."""
    await app.bot.set_my_commands(MENU)
    logger.info("command menu registered")
    try:
        await app.bot.set_my_short_description(SHORT_DESCRIPTION)
        await app.bot.set_my_description(DESCRIPTION)
        logger.info("bot description registered")
    except Exception as e:  # noqa: BLE001 — 설명 등록 실패가 봇을 막아선 안 된다
        logger.warning("set description failed: %s", e)


def main():
    config.validate()
    init_db()

    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    # 슬래시 명령 (상태 확인 / 실행 / 로그) + 사용법
    commands.register(app)
    help_cmd.register(app)

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
