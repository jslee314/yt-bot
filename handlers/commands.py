"""슬래시 명령 핸들러 — 폰에서 상태 확인하고 파이프라인을 굴리는 조작부.

채널(ko/ja)은 첫 인자로 고른다. 생략하면 ko.
  /status            모든 채널 한 장 (ko 전체 + 나머지 요약)
  /status ja         JA 만
  /queue [ch]        남은 작업 목록
  /run [ch] [force]  파이프라인 즉시 실행 (간격 제한 무시: force)
  /log [ch] [n]      최근 실행 로그 tail
  /stop              실행 중인 파이프라인 중단 (프로세스 단위라 채널 구분 없음)
  /stuck [ch]        채널에서 올라갔지만 공개도 예약도 안 된 영상 찾기
  /link [ch|all]     숏폼에 롱폼 '관련 동영상'을 걸기 위한 Studio 편집 링크
  /link done <id>    그 세트 연결 완료로 기록
  /help              명령 목록
"""

import json
import logging
import asyncio
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from config import (
    CHANNELS,
    DEFAULT_CHANNEL,
    LOCAL_YT_UPLOAD_DIR,
    PATH_PREPEND,
    PYTHON_BIN,
    FORCE_MONTHLY_LIMIT,
)
from handlers.common import auth_check
from services import pipeline
from services.runner import runner
from services import state
from services.state import get_decision, save_decision

logger = logging.getLogger(__name__)

STUCK_TOOL = Path(__file__).resolve().parent.parent / "tools" / "stuck_videos.py"

# 숏폼의 '관련 동영상'은 Data API에 필드가 없어 Studio에서만 걸 수 있다.
# 그래서 봇은 편집 화면으로 바로 가는 링크를 뿌리고, 완료 표시만 기록한다.
STUDIO_EDIT = "https://studio.youtube.com/video/{id}/edit"
TG_LIMIT = 3800  # 텔레그램 메시지 상한 4096 아래로

# 사용법(/help)은 handlers/help.py — 주제별 설명서와 상단 고정.


def _split_channel(args: list[str]) -> tuple[str | None, list[str]]:
    """첫 인자가 채널 코드면 떼어낸다. (채널 또는 None, 나머지 인자)"""
    if args and args[0].lower() in CHANNELS:
        return args[0].lower(), list(args[1:])
    return None, list(args)


@auth_check
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    market, _ = _split_channel(list(context.args or []))
    text = pipeline.summary(market) if market else pipeline.summary_all()
    await update.message.reply_text(text, parse_mode="HTML")


@auth_check
async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    market, _ = _split_channel(list(context.args or []))
    market = market or DEFAULT_CHANNEL
    ch = pipeline.channel(market)
    q = pipeline.queue(market)
    if not q:
        await update.message.reply_text(f"✅ {ch['label']} 남은 작업이 없습니다 (모두 업로드 완료).")
        return

    head = q[:15]
    lines = [f"📦 <b>{ch['label']} 남은 작업 {len(q)}개</b> (오래된 것부터)", ""]
    for i, s in enumerate(head, 1):
        mark = "▶️" if i == 1 else "  "
        lines.append(f"{mark} {i}. <code>{s.video_id}</code> — {s.stage}")
    if len(q) > len(head):
        lines.append(f"\n… 그 외 {len(q) - len(head)}개")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@auth_check
async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    market, rest = _split_channel(list(context.args or []))
    market = market or DEFAULT_CHANNEL
    ch = pipeline.channel(market)

    if not ch["orchestrated"]:
        await update.message.reply_text(
            f"⚙️ {ch['label']} {ch['name']} 는 아직 자동 파이프라인이 없습니다.\n"
            f"auto_pipeline.sh 에 CHANNEL 매개변수가 들어오면 /run {market} 가 연결됩니다.\n"
            f"지금 보이는 건 /status {market} · /queue {market} · /stuck {market} · /link {market}."
        )
        return

    if pipeline.is_running():
        await update.message.reply_text("⏳ 이미 실행 중입니다. /log 로 진행 상황을 보세요.")
        return

    force = bool(rest) and rest[0].lower() in ("force", "-f", "강제")

    if force:
        used = state.count_forced_runs()
        if used >= FORCE_MONTHLY_LIMIT:
            await update.message.reply_text(
                f"🚫 이번 달 <code>force</code> 한도를 다 썼습니다 "
                f"({used}/{FORCE_MONTHLY_LIMIT}회).\n\n"
                f"force 1회는 TTS 약 6,242자 + 이미지 + 채널 일일 쿼터 전부를 씁니다. "
                f"ElevenLabs Starter 월 40,000자 한도를 넘기지 않으려고 둔 상한입니다.\n\n"
                f"정말 더 돌려야 하면 <code>FORCE_MONTHLY_LIMIT</code> 를 올리고 봇을 재시작하세요.",
                parse_mode="HTML",
            )
            return

    if not force:
        remain = pipeline.throttle_remaining(market)
        if remain:
            days = int(pipeline.min_interval().total_seconds() // 86400) or 1
            await update.message.reply_text(
                f"⏱ 실행 간격 {days}일 제한으로 스킵됩니다 "
                f"({pipeline.human_delta(remain)} 남음).\n"
                f"무시하려면 <code>/run {market} force</code>\n\n"
                f"⚠️ 간격은 ElevenLabs 크레딧 상한에 맞춘 값입니다 — "
                f"당겨 돌리면 월 한도를 일찍 소진합니다.",
                parse_mode="HTML",
            )
            return

    target = pipeline.next_target(market)
    if not target:
        await update.message.reply_text(f"{ch['label']} 처리할 항목이 없습니다 (모두 업로드 완료).")
        return

    env_prefix = "YT_PIPELINE_FORCE=1 " if force else ""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(ch["log_dir"]) / f"botrun_{stamp}.log"
    # 채널마다 오케스트레이터가 다르다 — KO는 auto_pipeline.sh, JA는 mirror_pipeline.sh
    # (한국판 이미지를 재사용하고 TTS만 새 언어로 만든다).
    cmd = (
        f'PATH="{PATH_PREPEND}:$PATH" {env_prefix}'
        f'caffeinate -i /bin/bash "{ch["script"]}"'
    )
    pid = runner.spawn(cmd, log_path)
    if force:
        state.record_forced_run(market, target)
        left = max(0, FORCE_MONTHLY_LIMIT - state.count_forced_runs())
        force_note = f"⚠️ 간격 제한 무시 — 이번 달 force 잔여 {left}회"
    else:
        force_note = ""

    await update.message.reply_text(
        f"🚀 {ch['label']} 실행 시작 (pid {pid})\n"
        f"대상: <code>{target}</code>\n"
        f"{force_note}\n\n"
        f"완료되면 알림이 옵니다. /log 로 중간 확인, /stop 으로 중단.",
        parse_mode="HTML",
    )


@auth_check
async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    market, rest = _split_channel(list(context.args or []))
    market = market or DEFAULT_CHANNEL
    n = 40
    if rest:
        try:
            n = max(5, min(200, int(rest[0])))
        except ValueError:
            pass

    log = pipeline.latest_log(market)
    if not log:
        await update.message.reply_text(f"{pipeline.channel(market)['label']} 로그가 없습니다.")
        return

    verdict, _ = pipeline.log_verdict(log)
    body = pipeline.tail_log(log, n)[-3500:]  # 텔레그램 메시지 상한(4096) 안으로
    await update.message.reply_text(
        f"📄 <b>{log.name}</b> — {verdict}\n\n<pre>{pipeline._esc(body)}</pre>",
        parse_mode="HTML",
    )


@auth_check
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    procs = pipeline.running_procs()
    if not procs:
        await update.message.reply_text("실행 중인 파이프라인이 없습니다.")
        return

    await update.message.reply_text(f"🛑 중단 중… ({len(procs)}개 프로세스)")
    # pkill -f 는 오케스트레이터만 죽이고 자식(make_all.py·ffmpeg·TTS)은
    # 별도 세션에 있어 살아남았다 — 돈이 계속 나갔다. 그룹째 보낸다.
    r = await asyncio.to_thread(pipeline.stop_all)

    if r["survived"]:
        await update.message.reply_text(
            f"⚠️ 일부가 아직 살아 있습니다: "
            f"{', '.join(str(p) for p, _ in r['survived'])}\n"
            f"터미널에서 확인이 필요합니다."
        )
        return

    killed = f" (강제 종료 {len(r['killed'])}그룹)" if r["killed"] else ""
    await update.message.reply_text(
        f"🛑 중단 완료 — 프로세스 {len(r['procs'])}개, "
        f"그룹 {len(r['pgids'])}개 종료{killed}.\n"
        f"⚠️ 이미 쓴 TTS·이미지 비용은 환불되지 않습니다."
    )


@auth_check
async def cmd_stuck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """채널 전체를 훑어 private·예약없음 영상을 찾는다. YouTube API 호출이라 몇 초 걸린다.

    채널마다 토큰이 다르다(토큰 하나 = 채널 하나). yt-upload 의 config 가
    YOUTUBE_TOKEN_FILE / YOUTUBE_CREDENTIALS_FILE 환경변수를 읽으므로 그걸로 고른다.
    """
    market, _ = _split_channel(list(context.args or []))
    market = market or DEFAULT_CHANNEL
    ch = pipeline.channel(market)
    upload_dir = Path(LOCAL_YT_UPLOAD_DIR)

    token = upload_dir / ch["token"]
    if not token.exists():
        await update.message.reply_text(
            f"⚠️ {ch['label']} 토큰이 없습니다: <code>{token.name}</code>\n"
            f"{ch['account']} 계정으로 먼저 인증해야 합니다.",
            parse_mode="HTML",
        )
        return
    env = f'YOUTUBE_TOKEN_FILE="{token}"'
    cred = upload_dir / ch["credentials"]
    if cred.exists():  # 채널별 GCP 프로젝트(쿼터 분리)를 쓰면 여기로 들어온다
        env += f' YOUTUBE_CREDENTIALS_FILE="{cred}"'

    msg = await update.message.reply_text(
        f"🔎 {ch['label']} {ch['name']} 점검 중… (YouTube API 조회, 몇 초 걸립니다)"
    )
    cmd = f'cd "{upload_dir}" && {env} {PYTHON_BIN} "{STUCK_TOOL}" "{upload_dir}"'
    try:
        out, err = runner.execute(cmd, timeout=180)
        data = json.loads(out.strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001 — 사용자에게 원인을 그대로 보여주는 게 낫다
        logger.exception("stuck check failed (%s)", market)
        detail = (err or str(e))[-600:]
        await msg.edit_text(f"⚠️ 점검 실패\n<pre>{pipeline._esc(detail)}</pre>", parse_mode="HTML")
        return

    title = data.get("channel") or ch["name"]
    stuck = data.get("stuck", [])
    total = data.get("total", 0)
    if not stuck:
        await msg.edit_text(
            f"✅ {ch['label']} {pipeline._esc(title)} — 방치된 영상 없음\n"
            f"채널 {total}개 전부 공개됐거나 공개 예약돼 있습니다.",
            parse_mode="HTML",
        )
        return

    lines = [
        f"⚠️ <b>{ch['label']} {pipeline._esc(title)} — 올라갔지만 공개 안 된 영상 {len(stuck)}개</b> (채널 {total}개 중)",
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


def _uploaded_sets(market: str):
    """채널의 업로드된 세트를 최신순으로: (video_id, 롱폼 제목, 롱폼 yt id, [(번호, 숏폼 제목, 숏폼 yt id)])."""
    sets = []
    pkgs = sorted(Path(LOCAL_YT_UPLOAD_DIR, "outputs").glob("*/upload_package.json"), reverse=True)
    for pkg in pkgs:
        if not pipeline.is_market_id(pkg.parent.name, market):
            continue
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


async def _send_links(message, market: str, specific: str | None):
    ch = pipeline.channel(market)
    sets = _uploaded_sets(market)
    if specific:
        pending = [s for s in sets if s[0] == specific]
        if not pending:
            await message.reply_text(
                f"{ch['label']} 업로드된 세트 중에 <code>{specific}</code> 가 없습니다.", parse_mode="HTML"
            )
            return
    else:
        pending = [s for s in sets if get_decision(s[0], "related_linked") != "done"]
        if not pending:
            await message.reply_text(
                f"✅ {ch['label']} 미연결 세트가 없습니다. 모든 숏폼에 관련 동영상이 걸린 것으로 기록돼 있습니다."
            )
            return

    n_shorts = sum(len(s[3]) for s in pending)
    header = (
        f"🔗 <b>{ch['label']} {pipeline._esc(ch['name'])} — 숏폼 → 롱폼 관련 동영상</b>  "
        f"미연결 {len(pending)}세트 · 숏폼 {n_shorts}개\n"
        f"👤 이 채널은 <code>{ch['account']}</code> 계정입니다 — Studio 에 그 계정으로 로그인돼 있어야 링크가 열립니다.\n"
        "링크 → 편집 화면 오른쪽 <b>관련 동영상</b> → 아래 롱폼 선택 → 저장. "
        "채널에 <b>고급 기능 액세스</b>가 있어야 메뉴가 보입니다."
    )
    await _send_chunked(message, header, [_link_block(*s) for s in pending])


@auth_check
async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """숏폼마다 Studio 편집 링크를 띄운다. 거기서 '관련 동영상' → 롱폼 선택 → 저장."""
    args = list(context.args or [])

    if len(args) >= 2 and args[0].lower() == "done":
        save_decision(args[1], "related_linked", "done")
        await update.message.reply_text(
            f"✅ <code>{args[1]}</code> 관련 동영상 연결 완료로 기록했습니다.", parse_mode="HTML"
        )
        return

    if args and args[0].lower() == "all":
        for m in CHANNELS:
            await _send_links(update.message, m, None)
        return

    market, rest = _split_channel(args)
    specific = rest[0] if rest else None
    if specific and not market:
        market = pipeline.market_of(specific)  # /link YT-…-JA 처럼 id 만 왔을 때
    await _send_links(update.message, market or DEFAULT_CHANNEL, specific)


def register(app: Application):
    app.add_handler(CommandHandler("status", cmd_status, filters=filters.UpdateType.MESSAGE))
    app.add_handler(CommandHandler("queue", cmd_queue, filters=filters.UpdateType.MESSAGE))
    app.add_handler(CommandHandler("run", cmd_run, filters=filters.UpdateType.MESSAGE))
    app.add_handler(CommandHandler("log", cmd_log, filters=filters.UpdateType.MESSAGE))
    app.add_handler(CommandHandler("stop", cmd_stop, filters=filters.UpdateType.MESSAGE))
    app.add_handler(CommandHandler("stuck", cmd_stuck, filters=filters.UpdateType.MESSAGE))
    app.add_handler(CommandHandler("link", cmd_link, filters=filters.UpdateType.MESSAGE))
