"""슬래시 명령 핸들러 — 폰에서 상태 확인하고 파이프라인을 굴리는 조작부.

/status  현재 상태 한 장 요약
/queue   남은 작업 목록
/run     파이프라인 즉시 실행 (간격 제한 무시: /run force)
/log     최근 실행 로그 tail
/stop    실행 중인 파이프라인 중단
/stuck   채널에서 올라갔지만 공개도 예약도 안 된 영상 찾기
/link    숏폼에 롱폼 '관련 동영상'을 걸기 위한 Studio 편집 링크 목록
/help    명령 목록
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import (
    LOCAL_YT_UPLOAD_DIR,
    PATH_PREPEND,
    PIPELINE_LOG_DIR,
    PIPELINE_SCRIPT,
    PYTHON_BIN,
)
from handlers.common import auth_check
from services import pipeline
from services.runner import runner
from services.state import get_decision, save_decision

logger = logging.getLogger(__name__)

STUCK_TOOL = Path(__file__).resolve().parent.parent / "tools" / "stuck_videos.py"

# 숏폼의 '관련 동영상'은 Data API에 필드가 없어 Studio에서만 걸 수 있다.
# 그래서 봇은 편집 화면으로 바로 가는 링크를 뿌리고, 완료 표시만 기록한다.
STUDIO_EDIT = "https://studio.youtube.com/video/{id}/edit"
TG_LIMIT = 3800  # 텔레그램 메시지 상한 4096 아래로

HELP = """🤖 <b>yt-bot 명령</b>

/status — 파이프라인 상태 요약
/queue — 남은 작업 목록
/run — 지금 실행 (실행 간격 제한 적용)
/run force — 간격 제한 무시하고 실행
/log — 최근 로그 40줄
/log 100 — 최근 로그 100줄
/stop — 실행 중인 파이프라인 중단
/stuck — 올라갔지만 공개 안 된 영상 점검
/link — 숏폼→롱폼 관련 동영상 걸 Studio 링크
/link done YT-… — 그 세트 연결 완료로 기록
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
async def cmd_stuck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """채널 전체를 훑어 private·예약없음 영상을 찾는다. YouTube API 호출이라 몇 초 걸린다."""
    msg = await update.message.reply_text("🔎 채널 점검 중… (YouTube API 조회, 몇 초 걸립니다)")

    cmd = f'cd "{LOCAL_YT_UPLOAD_DIR}" && {PYTHON_BIN} "{STUCK_TOOL}" "{LOCAL_YT_UPLOAD_DIR}"'
    try:
        out, err = runner.execute(cmd, timeout=180)
        data = json.loads(out.strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001 — 사용자에게 원인을 그대로 보여주는 게 낫다
        logger.exception("stuck check failed")
        detail = (err or str(e))[-600:]
        await msg.edit_text(
            f"⚠️ 점검 실패\n<pre>{pipeline._esc(detail)}</pre>", parse_mode="HTML"
        )
        return

    stuck = data.get("stuck", [])
    total = data.get("total", 0)
    if not stuck:
        await msg.edit_text(
            f"✅ 방치된 영상 없음\n채널 {total}개 전부 공개됐거나 공개 예약돼 있습니다."
        )
        return

    lines = [
        f"⚠️ <b>올라갔지만 공개 안 된 영상 {len(stuck)}개</b> (채널 {total}개 중)",
        "",
    ]
    for v in stuck[:20]:
        lines.append(
            f"• [{v['privacy']}] {pipeline._esc(v['title'][:28])}\n"
            f"   업로드 {v['uploaded']} · https://youtu.be/{v['id']}"
        )
    if len(stuck) > 20:
        lines.append(f"\n… 그 외 {len(stuck) - 20}개")
    lines += [
        "",
        "이 상태로 두면 영원히 비공개입니다.",
        "YouTube Studio에서 공개하거나, Claude에 분산 예약을 요청하세요.",
    ]
    await msg.edit_text("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


def _uploaded_sets():
    """업로드된 세트를 최신순으로: (video_id, 롱폼 제목, 롱폼 yt id, [(번호, 숏폼 제목, 숏폼 yt id)])."""
    sets = []
    pkgs = sorted(Path(LOCAL_YT_UPLOAD_DIR, "outputs").glob("*/upload_package.json"), reverse=True)
    for pkg in pkgs:
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        lf = data.get("longform", {})
        if not lf.get("youtube_video_id"):
            continue
        shorts = [
            (i, s.get("title") or f"숏폼 {i}", s["youtube_video_id"])
            for i, s in enumerate(data.get("shorts", []), 1)
            if s.get("youtube_video_id")
        ]
        if shorts:
            sets.append((pkg.parent.name, lf.get("title", ""), lf["youtube_video_id"], shorts))
    return sets


def _link_block(video_id, long_title, long_id, shorts) -> str:
    lines = [
        f"📺 <b>{pipeline._esc(long_title[:30])}</b>  <code>{video_id}</code>",
        f"   연결할 롱폼: youtu.be/{long_id}",
    ]
    for i, title, sid in shorts:
        lines.append(f"   {i}. {pipeline._esc(title[:22])}")
        lines.append(f"      {STUDIO_EDIT.format(id=sid)}")
    lines.append(f"   끝나면 → <code>/link done {video_id}</code>")
    return "\n".join(lines)


async def _send_chunked(message, header: str, blocks: list[str]):
    """세트 단위로 끊어 4096자 상한을 넘지 않게 여러 메시지로 보낸다."""
    buf = header
    for b in blocks:
        if len(buf) + len(b) + 2 > TG_LIMIT:
            await message.reply_text(buf, parse_mode="HTML", disable_web_page_preview=True)
            buf = ""
        buf += ("\n\n" if buf else "") + b
    if buf:
        await message.reply_text(buf, parse_mode="HTML", disable_web_page_preview=True)


@auth_check
async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """숏폼마다 Studio 편집 링크를 띄운다. 거기서 '관련 동영상' → 롱폼 선택 → 저장."""
    args = list(context.args or [])

    if len(args) >= 2 and args[0].lower() == "done":
        save_decision(args[1], "related_linked", "done")
        await update.message.reply_text(f"✅ <code>{args[1]}</code> 관련 동영상 연결 완료로 기록했습니다.",
                                        parse_mode="HTML")
        return

    sets = _uploaded_sets()
    if args and args[0].lower() != "all":
        pending = [s for s in sets if s[0] == args[0]]
        if not pending:
            await update.message.reply_text(f"업로드된 세트 중에 <code>{args[0]}</code> 가 없습니다.",
                                            parse_mode="HTML")
            return
    else:
        pending = [s for s in sets if get_decision(s[0], "related_linked") != "done"]
        if not pending:
            await update.message.reply_text("✅ 미연결 세트가 없습니다. 모든 숏폼에 관련 동영상이 걸린 것으로 기록돼 있습니다.")
            return

    n_shorts = sum(len(s[3]) for s in pending)
    header = (
        f"🔗 <b>숏폼 → 롱폼 관련 동영상</b>  미연결 {len(pending)}세트 · 숏폼 {n_shorts}개\n"
        "링크를 열면 Studio 편집 화면 → 오른쪽 <b>관련 동영상</b> → 아래 롱폼 선택 → 저장.\n"
        "채널에 <b>고급 기능 액세스</b>가 있어야 메뉴가 보입니다 (Studio → 설정 → 채널 → 기능 사용 자격요건)."
    )
    await _send_chunked(update.message, header, [_link_block(*s) for s in pending])


@auth_check
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP, parse_mode="HTML")


def register(app: Application):
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("stuck", cmd_stuck))
    app.add_handler(CommandHandler("link", cmd_link))
    app.add_handler(CommandHandler(["help", "start"], cmd_help))
