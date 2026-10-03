"""파이프라인 상태 조회 — 봇의 /status, /queue, /log가 쓰는 단일 진실 공급원.

auto_pipeline.sh가 "upload_package.json에 youtube_video_id가 있나?"로 진행도를
추론하던 로직을 그대로 읽어온다. 추론 규칙을 한 군데 모아 두면 봇이 보여주는
상태와 파이프라인이 실제로 집는 대상이 어긋나지 않는다.
"""

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import (
    LOCAL_YT_PRODUCTION_DIR,
    LOCAL_YT_SCRIPT_DIR,
    LOCAL_YT_UPLOAD_DIR,
    PIPELINE_LOG_DIR,
    PIPELINE_STATE_FILE,
    STALE_WARN_DAYS,
)

KST = timezone(timedelta(hours=9))

# 영상 1건의 진행 단계
STAGE_QUEUED = "대기"
STAGE_PRODUCED = "영상완성"
STAGE_PACKAGED = "메타생성"
STAGE_UPLOADED = "업로드완료"


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


def all_video_ids() -> list[str]:
    out = _script_outputs()
    if not out.is_dir():
        return []
    return sorted(p.name for p in out.glob("YT-*-*") if p.is_dir())


def queue() -> list[VideoState]:
    """미업로드 영상 목록 (파이프라인이 집는 순서 = 오래된 것부터)."""
    return [s for s in (video_state(v) for v in all_video_ids()) if not s.is_uploaded]


def uploaded_count() -> int:
    return sum(1 for v in all_video_ids() if _uploaded_video_id(v))


def next_target() -> str | None:
    """auto_pipeline.sh가 다음 실행 시 집을 video_id."""
    q = queue()
    return q[0].video_id if q else None


# ── 실행 이력 ──────────────────────────────────────────────


def last_success() -> datetime | None:
    """state 파일에 기록된 마지막 성공 시각."""
    if not PIPELINE_STATE_FILE.exists():
        return None
    try:
        ts = int(PIPELINE_STATE_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    return datetime.fromtimestamp(ts, KST)


def log_files() -> list[Path]:
    if not PIPELINE_LOG_DIR.is_dir():
        return []
    return sorted(PIPELINE_LOG_DIR.glob("*.log"))


def latest_log() -> Path | None:
    logs = log_files()
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


def is_running() -> bool:
    """auto_pipeline.sh가 지금 돌고 있는지 — 프로세스 테이블로 확인."""
    import subprocess

    try:
        out = subprocess.run(
            ["pgrep", "-f", "auto_pipeline.sh"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return out.returncode == 0 and bool(out.stdout.strip())


def throttle_remaining() -> timedelta | None:
    """24시간 throttle이 남아 있으면 남은 시간, 없으면 None."""
    last = last_success()
    if last is None:
        return None
    elapsed = datetime.now(KST) - last
    if elapsed >= timedelta(hours=24):
        return None
    return timedelta(hours=24) - elapsed


def is_stale() -> bool:
    """마지막 성공이 STALE_WARN_DAYS를 넘었는지 — 조용히 죽은 상태 감지."""
    last = last_success()
    if last is None:
        return True
    return datetime.now(KST) - last > timedelta(days=STALE_WARN_DAYS)


def summary() -> str:
    """/status 본문 (HTML)."""
    now = datetime.now(KST)
    q = queue()
    done = uploaded_count()
    total = len(all_video_ids())

    lines = [f"📊 <b>파이프라인 상태</b>  ({now.strftime('%m/%d %H:%M')} KST)", ""]

    # 실행 여부
    if is_running():
        lines.append("🟢 <b>지금 실행 중</b>")
    else:
        last = last_success()
        if last is None:
            lines.append("⚪️ 성공 기록 없음")
        else:
            days = (now - last).days
            hours = int((now - last).total_seconds() // 3600)
            mark = "🔴" if is_stale() else "⚪️"
            ago = f"{days}일 전" if days >= 1 else f"{hours}시간 전"
            lines.append(
                f"{mark} 마지막 성공: {last.strftime('%Y-%m-%d %H:%M')} ({ago})"
            )
            if is_stale():
                lines.append(
                    f"   ⚠️ {STALE_WARN_DAYS}일 넘게 성공이 없습니다 — 점검 필요"
                )

    # 최근 로그 판정
    log = latest_log()
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

    # throttle
    remain = throttle_remaining()
    if remain:
        h = int(remain.total_seconds() // 3600)
        m = int((remain.total_seconds() % 3600) // 60)
        lines.append(f"⏱ 24시간 제한: {h}시간 {m}분 남음 (/run force로 무시 가능)")

    return "\n".join(lines)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
