"""슬래시 명령 핸들러 — 폰에서 상태 확인하고 파이프라인을 굴리는 조작부.

/status  현재 상태 한 장 요약
/queue   남은 작업 목록
/run     파이프라인 즉시 실행 (간격 제한 무시: /run force)
/log     최근 실행 로그 tail
/stop    실행 중인 파이프라인 중단
/help    명령 목록
"""

import logging
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import PATH_PREPEND, PIPELINE_LOG_DIR, PIPELINE_SCRIPT
from handlers.common import auth_check
from services import pipeline
from services.runner import runner

logger = logging.getLogger(__name__)

HELP = """🤖 <b>yt-bot 명령</b>

/status — 파이프라인 상태 요약
/queue — 남은 작업 목록
/run — 지금 실행 (실행 간격 제한 적용)
/run force — 간격 제한 무시하고 실행
/log — 최근 로그 40줄
/log 100 — 최근 로그 100줄
/stop — 실행 중인 파이프라인 중단
/help — 이 도움말

영상이 완성되거나 실패하면 알림이 자동으로 옵니다."""


@auth_check
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(pipeline.summary(), parse_mode="HTML")


@auth_check
async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = pipeline.queue()
    if not q:
        await update.message.reply_text("✅ 남은 작업이 없습니다 (모두 업로드 완료).")
        return

    head = q[:15]
    lines = [f"📦 <b>남은 작업 {len(q)}개</b> (오래된 것부터)", ""]
    for i, s in enumerate(head, 1):
        mark = "▶️" if i == 1 else "  "
        lines.append(f"{mark} {i}. <code>{s.video_id}</code> — {s.stage}")
    if len(q) > len(head):
        lines.append(f"\n… 그 외 {len(q) - len(head)}개")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@auth_check
async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if pipeline.is_running():
        await update.message.reply_text(
            "⏳ 이미 실행 중입니다. /log 로 진행 상황을 보세요."
        )
        return

    force = bool(context.args) and context.args[0].lower() in ("force", "-f", "강제")

    if not force:
        remain = pipeline.throttle_remaining()
        if remain:
            days = int(pipeline.min_interval().total_seconds() // 86400) or 1
            await update.message.reply_text(
                f"⏱ 실행 간격 {days}일 제한으로 스킵됩니다 "
                f"({pipeline.human_delta(remain)} 남음).\n"
                f"무시하려면 <code>/run force</code>\n\n"
                f"⚠️ 간격은 ElevenLabs 크레딧 상한에 맞춘 값입니다 — "
                f"당겨 돌리면 월 한도를 일찍 소진합니다.",
                parse_mode="HTML",
            )
            return

    target = pipeline.next_target()
    if not target:
        await update.message.reply_text("처리할 항목이 없습니다 (모두 업로드 완료).")
        return

    # force면 state 파일을 비워 throttle을 통과시킨다 (스크립트 수정 없이)
    env_prefix = ""
    if force:
        env_prefix = "YT_PIPELINE_FORCE=1 "

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = PIPELINE_LOG_DIR / f"botrun_{stamp}.log"
    cmd = (
        f'PATH="{PATH_PREPEND}:$PATH" {env_prefix}'
        f'caffeinate -i /bin/bash "{PIPELINE_SCRIPT}"'
    )
    pid = runner.spawn(cmd, log_path)

    await update.message.reply_text(
        f"🚀 실행 시작 (pid {pid})\n"
        f"대상: <code>{target}</code>\n"
        f"{'⚠️ 간격 제한 무시 — 크레딧 소진 주의' if force else ''}\n\n"
        f"완료되면 알림이 옵니다. /log 로 중간 확인 가능.",
        parse_mode="HTML",
    )


@auth_check
async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = 40
    if context.args:
        try:
            n = max(5, min(200, int(context.args[0])))
        except ValueError:
            pass

    log = pipeline.latest_log()
    if not log:
        await update.message.reply_text("로그가 없습니다.")
        return

    verdict, _ = pipeline.log_verdict(log)
    body = pipeline.tail_log(log, n)
    # 텔레그램 메시지 상한(4096) 안으로
    body = body[-3500:]
    await update.message.reply_text(
        f"📄 <b>{log.name}</b> — {verdict}\n\n<pre>{pipeline._esc(body)}</pre>",
        parse_mode="HTML",
    )


@auth_check
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not pipeline.is_running():
        await update.message.reply_text("실행 중인 파이프라인이 없습니다.")
        return
    out, err = runner.execute("pkill -f auto_pipeline.sh", timeout=30)
    await update.message.reply_text(
        "🛑 중단 신호를 보냈습니다.\n"
        "⚠️ 진행 중이던 TTS/이미지 생성 비용은 환불되지 않습니다."
    )


@auth_check
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP, parse_mode="HTML")


def register(app: Application):
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler(["help", "start"], cmd_help))
