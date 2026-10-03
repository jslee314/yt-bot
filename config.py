"""yt-bot 설정 — 봇이 파이프라인과 같은 맥에서 직접 돌는 로컬 모드.

원래 설계(클라우드 VM + SSH 역접속)는 폐기했다. bot.py가 롱폴링이므로
맥에서 돌리면 텔레그램으로 나가는 연결만 쓰고, DDNS·22번 포트 개방·
클라우드 VM이 전부 불필요하다.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Telegram ───────────────────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))

# ── 프로젝트 경로 ──────────────────────────────────────────
PROJECTS_DIR = Path(os.getenv("PROJECTS_DIR", "/Users/jslee/Projects"))

LOCAL_YT_SCRIPT_DIR = os.getenv("LOCAL_YT_SCRIPT_DIR", str(PROJECTS_DIR / "yt-script"))
LOCAL_YT_PRODUCTION_DIR = os.getenv(
    "LOCAL_YT_PRODUCTION_DIR", str(PROJECTS_DIR / "yt-production_whisk")
)
LOCAL_YT_UPLOAD_DIR = os.getenv("LOCAL_YT_UPLOAD_DIR", str(PROJECTS_DIR / "yt-upload"))

# ── 파이프라인 오케스트레이션 ──────────────────────────────
# 오케스트레이터는 별도 저장소(yt-pipeline)에 있다.
LOCAL_YT_PIPELINE_DIR = Path(
    os.getenv("LOCAL_YT_PIPELINE_DIR", str(PROJECTS_DIR / "yt-pipeline"))
)
PIPELINE_SCRIPT = os.getenv(
    "PIPELINE_SCRIPT", str(LOCAL_YT_PIPELINE_DIR / "auto_pipeline.sh")
)
PIPELINE_LOG_DIR = Path(
    os.getenv("PIPELINE_LOG_DIR", str(LOCAL_YT_PIPELINE_DIR / "logs"))
)
PIPELINE_STATE_FILE = Path(
    os.getenv("PIPELINE_STATE_FILE", str(LOCAL_YT_PIPELINE_DIR / "auto_pipeline.state"))
)

# ── 실행 환경 ──────────────────────────────────────────────
# 파이프라인이 쓰는 인터프리터. yt-production/yt-upload는 python.org 3.10에
# 의존성이 깔려 있어 `python3`(homebrew)로 돌리면 ImportError가 난다.
PYTHON_BIN = os.getenv("PYTHON_BIN", "/usr/local/bin/python3")

# ffmpeg/ffprobe가 homebrew에 있으므로 PATH 앞에 붙인다 (launchd는 PATH가 빈약).
PATH_PREPEND = os.getenv("PATH_PREPEND", "/opt/homebrew/bin:/usr/local/bin")

# execute() 기본 타임아웃 (초). 업로드 5개가 30분 넘을 수 있어 넉넉하게.
SHELL_TIMEOUT = int(os.getenv("SHELL_TIMEOUT", "1800"))

# 마지막 성공 이후 이 일수를 넘기면 /status가 경고를 띄운다.
STALE_WARN_DAYS = int(os.getenv("STALE_WARN_DAYS", "3"))

# ── 상태 DB ────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", str(Path(__file__).parent / "state.db"))


def validate():
    """필수 설정 누락 시 즉시 종료 — launchd 로그에 원인이 남도록."""
    missing = []
    if not BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        sys.exit(
            f"[FATAL] .env에 다음 값이 없습니다: {', '.join(missing)}\n"
            f"  .env.example을 복사해 채우세요: cp .env.example .env"
        )
