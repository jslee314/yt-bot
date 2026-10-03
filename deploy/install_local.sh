#!/bin/bash
# ─────────────────────────────────────────────────────────────
# yt-bot 로컬 설치 — 맥에 상주시킨다.
#
#   bash deploy/install_local.sh
#
# .env가 없으면 먼저 만들라고 안내하고 멈춘다.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$BOT_DIR/deploy/com.jslee.yt-bot.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.jslee.yt-bot.plist"
LABEL="com.jslee.yt-bot"
PY="${PYTHON_BIN:-/usr/local/bin/python3}"

cd "$BOT_DIR"

# ── 1. .env 확인 ───────────────────────────────────────────
if [ ! -f .env ]; then
    cat <<'MSG'
[중단] .env가 없습니다. 먼저 텔레그램 봇을 만들고 .env를 채우세요.

  1) 텔레그램에서 @BotFather 검색 → /newbot → 이름 입력 → 토큰 복사
  2) 방금 만든 봇과의 대화를 열어 아무 메시지나 전송
  3) chat_id 확인:
       curl -s "https://api.telegram.org/bot<토큰>/getUpdates" \
         | grep -o '"id":[0-9-]*' | head -1
  4) 설정 파일 작성:
       cp .env.example .env && open -e .env
  5) 다시 실행:
       bash deploy/install_local.sh
MSG
    exit 1
fi

# ── 2. venv + 의존성 ──────────────────────────────────────
if [ ! -x .venv/bin/python ]; then
    echo "[1/4] venv 생성 ($PY)"
    "$PY" -m venv .venv
fi
echo "[2/4] 의존성 설치"
.venv/bin/pip -q install -r requirements.txt

# ── 3. 설정 검증 (토큰이 실제로 유효한지 확인) ────────────
echo "[3/4] 텔레그램 토큰 검증"
.venv/bin/python - <<'PYEOF'
import sys

import requests
from dotenv import load_dotenv
import os

load_dotenv()
token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
if not token or not chat_id:
    sys.exit("[FATAL] .env의 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID를 채우세요.")

r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15)
if not r.ok or not r.json().get("ok"):
    sys.exit(f"[FATAL] 토큰이 유효하지 않습니다: {r.text[:200]}")
name = r.json()["result"]["username"]
print(f"  봇 확인: @{name}")

r = requests.post(
    f"https://api.telegram.org/bot{token}/sendMessage",
    json={"chat_id": chat_id, "text": "✅ yt-bot 설치 완료 — /status 로 상태를 확인하세요."},
    timeout=15,
)
if not r.ok:
    sys.exit(
        f"[FATAL] chat_id({chat_id})로 메시지를 보낼 수 없습니다: {r.text[:200]}\n"
        "  봇과의 대화에서 먼저 아무 메시지나 보냈는지 확인하세요."
    )
print("  테스트 메시지 전송 성공")
PYEOF

# ── 4. launchd 등록 ───────────────────────────────────────
echo "[4/4] launchd 등록"
mkdir -p "$(dirname "$PLIST_DST")"
cp "$PLIST_SRC" "$PLIST_DST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"

sleep 2
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
    echo
    echo "✅ 설치 완료. 폰에서 봇에게 /status 를 보내보세요."
    echo "   로그:    tail -f $BOT_DIR/bot.log"
    echo "   재시작:  launchctl kickstart -k gui/$(id -u)/$LABEL"
    echo "   제거:    launchctl bootout gui/$(id -u)/$LABEL"
else
    echo "⚠️ 등록 확인 실패. 로그를 보세요: $BOT_DIR/bot.log"
    exit 1
fi
