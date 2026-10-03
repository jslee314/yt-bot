"""파이프라인 상태 조회 — 봇의 /status, /queue, /log가 쓰는 단일 진실 공급원.

auto_pipeline.sh가 "upload_package.json에 youtube_video_id가 있나?"로 진행도를
추론하던 로직을 그대로 읽어온다. 추론 규칙을 한 군데 모아 두면 봇이 보여주는
상태와 파이프라인이 실제로 집는 대상이 어긋나지 않는다.

채널(시장)은 config.CHANNELS 로 구분한다. 조회 함수는 market 인자를 받고
기본값은 DEFAULT_CHANNEL(ko) — 기존 호출부는 바꾸지 않아도 동작한다.
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import (
    CHANNELS,
    DEFAULT_CHANNEL,
    LOCAL_YT_PRODUCTION_DIR,
    LOCAL_YT_SCRIPT_DIR,
    LOCAL_YT_UPLOAD_DIR,
    PIPELINE_SCRIPT,
    STALE_WARN_DAYS,
)

KST = timezone(timedelta(hours=9))

# 영상 1건의 진행 단계
STAGE_QUEUED = "대기"
STAGE_PRODUCED = "영상완성"
STAGE_PACKAGED = "메타생성"
STAGE_UPLOADED = "업로드완료"

# 채널별 영상 ID 형식. glob("YT-*-*")의 `*`는 하이픈을 넘어가므로
# YT-20260425-004-JA 같은 다른 시장용 폴더까지 잡힌다. lib/select_target.py 의
# 대상 선택과 같은 기준을 써서 /queue · /status 가 실제 대상과 어긋나지 않게 한다.
_ID_RE = {m: re.compile(c["id_re"]) for m, c in CHANNELS.items()}


def channel(market: str) -> dict:
    """market 코드 → 채널 설정. 모르는 코드는 어떤 코드가 있는지 알려주며 실패한다."""
    try:
        return CHANNELS[market]
    except KeyError:
        raise ValueError(f"알 수 없는 채널 '{market}' — 가능: {', '.join(CHANNELS)}") from None


def is_market_id(video_id: str, market: str) -> bool:
    return bool(_ID_RE[market].match(video_id))


def market_of(video_id: str) -> str | None:
    """video_id 형식만으로 채널을 알아낸다 (/link done 처럼 id만 오는 자리)."""
    for m, rx in _ID_RE.items():
        if rx.match(video_id):
            return m
    return None


@dataclass
class VideoState:
    video_id: str
    stage: str
    youtube_url: str | None = None

    @property
    def is_uploaded(self) -> bool:
        return self.stage == STAGE_UPLOADED


def _script_outputs() -> Path:
    return Path(LOCAL_YT_SCRIPT_DIR) / "outputs"


def _upload_outputs() -> Path:
    return Path(LOCAL_YT_UPLOAD_DIR) / "outputs"


def _runs_dir() -> Path:
    return Path(LOCAL_YT_PRODUCTION_DIR) / "runs"


def _uploaded_video_id(video_id: str) -> str | None:
    """업로드 완료면 YouTube video id, 아니면 None. auto_pipeline.sh와 동일 규칙."""
    pkg = _upload_outputs() / video_id / "upload_package.json"
    if not pkg.exists():
        return None
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data.get("longform", {}).get("youtube_video_id") or None


def _has_final_video(video_id: str) -> bool:
    run_dir = _runs_dir() / f"{video_id}_script"
    return run_dir.is_dir() and any(run_dir.glob("*final*.mp4"))


def video_state(video_id: str) -> VideoState:
    yt_id = _uploaded_video_id(video_id)
    if yt_id:
        return VideoState(video_id, STAGE_UPLOADED, f"https://youtu.be/{yt_id}")
    if (_upload_outputs() / video_id / "upload_package.json").exists():
        return VideoState(video_id, STAGE_PACKAGED)
    if _has_final_video(video_id):
        return VideoState(video_id, STAGE_PRODUCED)
    return VideoState(video_id, STAGE_QUEUED)


def all_video_ids(market: str = DEFAULT_CHANNEL) -> list[str]:
    out = _script_outputs()
    if not out.is_dir():
        return []
    rx = _ID_RE[market]
    return sorted(p.name for p in out.glob("YT-*-*") if p.is_dir() and rx.match(p.name))


def queue(market: str = DEFAULT_CHANNEL) -> list[VideoState]:
    """미업로드 영상 목록 (파이프라인이 집는 순서 = 오래된 것부터)."""
    return [s for s in (video_state(v) for v in all_video_ids(market)) if not s.is_uploaded]


def uploaded_count(market: str = DEFAULT_CHANNEL) -> int:
    return sum(1 for v in all_video_ids(market) if _uploaded_video_id(v))


def next_target(market: str = DEFAULT_CHANNEL) -> str | None:
    """auto_pipeline.sh가 다음 실행 시 집을 video_id."""
    q = queue(market)
    return q[0].video_id if q else None


# ── 실행 이력 ──────────────────────────────────────────────


def last_success(market: str = DEFAULT_CHANNEL) -> datetime | None:
    """state 파일에 기록된 마지막 성공 시각."""
    state = Path(channel(market)["state"])
    if not state.exists():
        return None
    try:
        ts = int(state.read_text().strip())
    except (ValueError, OSError):
        return None
    return datetime.fromtimestamp(ts, KST)


# 실행 로그가 아닌 것들 — launchd 자체 오류 로그는 파이프라인 판정 대상이 아니다.
_NOT_RUN_LOGS = ("launchd.out.log", "launchd.err.log")


def log_files(market: str = DEFAULT_CHANNEL) -> list[Path]:
    """실행 로그를 오래된 것부터. 이름순이 아니라 mtime순으로 정렬한다.

    파일명이 `20260519_030000.log`(cron 시절), `botrun_20261003_160000.log`(봇 실행),
    `launchd.err.log`(launchd)로 섞여 있어 이름순 정렬은 숫자/영문 순서 때문에
    실제 시간순과 어긋난다.
    """
    log_dir = Path(channel(market)["log_dir"])
    if not log_dir.is_dir():
        return []
    logs = [p for p in log_dir.glob("*.log") if p.is_file() and p.name not in _NOT_RUN_LOGS]
    return sorted(logs, key=lambda p: p.stat().st_mtime)


def latest_log(market: str = DEFAULT_CHANNEL) -> Path | None:
    logs = log_files(market)
    return logs[-1] if logs else None


def log_verdict(log_path: Path) -> tuple[str, str]:
    """로그 1개를 (판정, 핵심줄)로 요약. 판정: 성공/실패/스킵/진행중/불명."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return "불명", str(e)

    if "자동 파이프라인 완료" in text:
        return "성공", _last_match(text, r"^\[.*\] 자동 파이프라인 완료.*$")
    errors = re.findall(r"^\[ERROR\].*$", text, re.MULTILINE)
    if errors:
        return "실패", errors[-1]
    if "오늘은 스킵" in text:
        return "스킵", _last_match(text, r"^\[INFO\] 마지막 성공.*$")
    if "처리할 항목 없음" in text:
        return "스킵", "모든 영상 업로드 완료 — 처리할 항목 없음"
    return "진행중", _last_nonempty(text)


def _last_match(text: str, pattern: str) -> str:
    m = re.findall(pattern, text, re.MULTILINE)
    return m[-1].strip() if m else ""


def _last_nonempty(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()[:300]
    return ""


def tail_log(log_path: Path, lines: int = 30) -> str:
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"(로그 읽기 실패: {e})"
    return "\n".join(content.splitlines()[-lines:])


# 제작이 돌고 있다고 볼 프로세스 패턴. auto_pipeline.sh만 보면
# batch_run.sh / resume_build.sh / run.sh 를 직접 띄운 수동 실행을 놓친다.
# 프로세스 단위라 채널을 가르지 못한다 — 어느 채널이든 "돌고 있음"이다.
_RUNNING_PATTERN = r"auto_pipeline\.sh|batch_run\.sh|resume_build\.sh|make_all\.py"


def is_running() -> bool:
    """제작 파이프라인이 지금 돌고 있는지 — 프로세스 테이블로 확인."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", _RUNNING_PATTERN], capture_output=True, text=True, timeout=10
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return out.returncode == 0 and bool(out.stdout.strip())


def running_detail() -> str:
    """돌고 있는 make_all.py의 대상(run-dir)을 뽑아 '롱폼 YT-…' 식으로 요약."""
    try:
        out = subprocess.run(
            ["pgrep", "-fl", r"make_all\.py"], capture_output=True, text=True, timeout=10
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    m = re.search(r"--run-dir\s+runs/(\S+)", out.stdout)
    if not m:
        return ""
    run = m.group(1)
    kind = "숏폼" if "_shorts_" in run else "롱폼"
    return f"{kind} {run.split('_')[0]}"


_INTERVAL_RE = re.compile(r'MIN_INTERVAL="\$\{YT_PIPELINE_MIN_INTERVAL:-(\d+)\}"')
_INTERVAL_FALLBACK = timedelta(days=10)


def min_interval() -> timedelta:
    """실행 간격 — auto_pipeline.sh의 기본값을 읽어온다.

    간격은 비용 정책(ElevenLabs 크레딧 상한)에 묶여 있어 바뀐다. 봇이 숫자를
    복제하면 스크립트가 바뀔 때마다 /status가 거짓을 말하게 되므로,
    스크립트를 단일 진실 공급원으로 두고 여기서 읽는다.
    ElevenLabs 계정은 채널이 공유하므로 간격은 채널 합산으로 봐야 한다.
    """
    env = os.environ.get("YT_PIPELINE_MIN_INTERVAL")
    if env and env.isdigit():
        return timedelta(seconds=int(env))
    try:
        text = Path(PIPELINE_SCRIPT).read_text(encoding="utf-8")
    except OSError:
        return _INTERVAL_FALLBACK
    m = _INTERVAL_RE.search(text)
    return timedelta(seconds=int(m.group(1))) if m else _INTERVAL_FALLBACK


def throttle_remaining(market: str = DEFAULT_CHANNEL) -> timedelta | None:
    """실행 간격 제한이 남아 있으면 남은 시간, 없으면 None."""
    last = last_success(market)
    if last is None:
        return None
    interval = min_interval()
    elapsed = datetime.now(KST) - last
    if elapsed >= interval:
        return None
    return interval - elapsed


def human_delta(td: timedelta) -> str:
    """timedelta를 '3일 5시간' 같은 한국어 표기로."""
    total = int(td.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}일 {hours}시간"
    if hours:
        return f"{hours}시간 {minutes}분"
    return f"{minutes}분"


def is_stale(market: str = DEFAULT_CHANNEL) -> bool:
    """마지막 성공이 STALE_WARN_DAYS를 넘었는지 — 조용히 죽은 상태 감지."""
    last = last_success(market)
    if last is None:
        return True
    return datetime.now(KST) - last > timedelta(days=STALE_WARN_DAYS)


def summary(market: str = DEFAULT_CHANNEL) -> str:
    """/status <채널> 본문 (HTML)."""
    ch = channel(market)
    now = datetime.now(KST)
    q = queue(market)
    done = uploaded_count(market)
    total = len(all_video_ids(market))

    lines = [f"📊 <b>{ch['label']} {ch['name']}</b>  ({now.strftime('%m/%d %H:%M')} KST)", ""]

    # 실행 여부 — 오케스트레이터가 없는 채널은 state·로그·간격이 모두 없다.
    if not ch["orchestrated"]:
        lines.append("⚙️ 오케스트레이터 미구성 — 자동 실행·알림 없음")
        lines.append("   (auto_pipeline.sh 에 CHANNEL 매개변수가 들어오면 연결)")
    elif is_running():
        detail = running_detail()
        lines.append(f"🟢 <b>지금 실행 중</b>{' — ' + detail if detail else ''}")
    else:
        last = last_success(market)
        if last is None:
            lines.append("⚪️ 성공 기록 없음")
        else:
            days = (now - last).days
            hours = int((now - last).total_seconds() // 3600)
            mark = "🔴" if is_stale(market) else "⚪️"
            ago = f"{days}일 전" if days >= 1 else f"{hours}시간 전"
            lines.append(f"{mark} 마지막 성공: {last.strftime('%Y-%m-%d %H:%M')} ({ago})")
            if is_stale(market):
                lines.append(f"   ⚠️ {STALE_WARN_DAYS}일 넘게 성공이 없습니다 — 점검 필요")

    # 최근 로그 판정
    log = latest_log(market)
    if log:
        verdict, detail = log_verdict(log)
        icon = {"성공": "✅", "실패": "❌", "스킵": "⏭", "진행중": "⏳"}.get(verdict, "❔")
        stamp = datetime.fromtimestamp(log.stat().st_mtime, KST).strftime("%m/%d %H:%M")
        lines += ["", f"{icon} 최근 실행 ({stamp}): <b>{verdict}</b>"]
        if detail:
            lines.append(f"   <code>{_esc(detail[:200])}</code>")

    # 큐
    lines += ["", f"📦 대본 {total}개 · 업로드 완료 {done}개 · 남은 작업 {len(q)}개"]
    if q:
        nxt = q[0]
        lines.append(f"▶️ 다음 대상: <b>{nxt.video_id}</b> ({nxt.stage})")
    else:
        lines.append("▶️ 다음 대상: 없음 (모두 완료)")

    # 실행 간격 제한
    if ch["orchestrated"]:
        interval_days = int(min_interval().total_seconds() // 86400) or 1
        remain = throttle_remaining(market)
        if remain:
            when = (now + remain).strftime("%m/%d %H:%M")
            lines.append(f"⏱ 실행 간격 {interval_days}일 — {human_delta(remain)} 남음 (~{when})")
            lines.append(f"   당겨 돌리려면 /run {market} force")
        else:
            lines.append(f"⏱ 실행 간격 {interval_days}일 — 지금 실행 가능")

    return "\n".join(lines)


def summary_compact(market: str) -> str:
    """다른 채널을 /status 한 장에 덧붙일 때 쓰는 4줄 요약."""
    ch = channel(market)
    q = queue(market)
    done = uploaded_count(market)
    total = len(all_video_ids(market))
    lines = [f"📊 <b>{ch['label']} {ch['name']}</b>"]
    if not ch["orchestrated"]:
        lines.append("   ⚙️ 오케스트레이터 미구성")
    lines.append(f"   📦 대본 {total}개 · 업로드 완료 {done}개 · 남은 작업 {len(q)}개")
    if q:
        lines.append(f"   ▶️ 다음 대상: <code>{q[0].video_id}</code>")
    lines.append(f"   자세히: /status {market}")
    return "\n".join(lines)


def summary_all() -> str:
    """/status 인자 없음 — 기본 채널은 전체, 나머지 채널은 요약으로 한 장에."""
    parts = [summary(DEFAULT_CHANNEL)]
    parts += [summary_compact(m) for m in CHANNELS if m != DEFAULT_CHANNEL]
    return "\n\n".join(parts)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
