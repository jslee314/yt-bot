# yt-bot — Telegram 봇 설계서

## 1. 개요

YouTube 자동화 파이프라인(yt-script, yt-production, yt-upload)의 **사후 승인/수정 채널**.
파이프라인은 항상 끝까지 돌고(1번 후보 자동 선택), 봇은 결과를 알려주고 수정이 필요하면 처리한다.

### 핵심 원칙

- **파이프라인은 멈추지 않는다** — 봇 응답을 기다리지 않음. 1번 후보로 완주.
- **봇은 사후 채널이다** — 알림 확인 → 수정 필요하면 선택 → 재생성 트리거
- **수정 안 하면 그냥 무시** — 이미 완성되어 있음
- **Single user** — 나 혼자 사용. 인증은 chat_id 고정값으로 처리.

### 아키텍처

```
[로컬 PC]                          [Oracle Cloud]           [Telegram]
                                    yt-bot 서버
파이프라인 완료                      (python-telegram-bot
  → Telegram Bot API                 + FastAPI 경량 서버
    직접 호출 (HTTP) ──────────────→  + SSH 클라이언트)  ──→  📱 알림
                                                              │
                                                              ↓
                                                          사용자 응답
                                                              │
                                    봇이 callback 처리  ←─────┘
                                      ↓
                                    SSH로 로컬 PC 접속
                                      → 해당 스텝만 재실행
                                      → 결과 알림 전송
```

---

## 2. 개입 지점 상세

### 개입 지점 목록 (확정)

| # | 개입 지점 | 타이밍 | 프로젝트 |
|---|----------|--------|---------|
| 1 | 훅 선택 | yt-script 완료 후 | yt-script |
| 2 | 썸네일 문구 선택 | yt-script 완료 후 | yt-production |
| 3 | 제목 확인/수정 | yt-script 완료 후 | yt-upload |
| 4 | 업로드 트리거 | yt-production 완료 후 | yt-upload |
| 5 | 노출 시각 지정 | 업로드 트리거 시 | yt-upload |

### 알림 타이밍 정리

파이프라인 완료 시점에 맞춰 2번의 알림이 발생:

```
[알림 1] yt-script 완료 시
├── 훅 후보 5개 → 현재 선택: 1번 (자동)
├── 썸네일 문구 후보 3~5개 → 현재 선택: 1번 (자동)
├── 제목 → 현재: AI 생성 제목
└── "수정 필요하면 아래 버튼 탭"

[알림 2] yt-production 완료 시
├── 최종 영상 정보 (길이, 컷 수)
├── 썸네일 미리보기 (thumbnail.png 전송)
├── 업로드 버튼
└── 노출 시각 입력 안내
```

---

## 3. 각 개입 지점별 인터랙션 패턴

### 3-1. 알림 1: yt-script 완료

봇이 보내는 메시지:

```
📝 대본 완성 — YT-20260313-001

제목: 아침 90분이 하루를 바꾼다
글자수: 6,432자 | 챕터: 5개 | 숏폼: 4개

━━━ 훅 (현재: #1 자동선택) ━━━
1️⃣ 여러분, 혹시 아침에 일어나자마자 핸드폰부터 확인하시나요?
2️⃣ 매일 아침 반복되는 이 습관, 당신의 뇌를 망치고 있습니다
3️⃣ 아침 90분이 하루의 승부를 가릅니다
4️⃣ 핸드폰 알람 끄고 가장 먼저 하는 행동이 뭔가요?
5️⃣ 기상 후 90분, 이 시간을 어떻게 쓰느냐가 전부입니다

━━━ 썸네일 문구 (현재: #1 자동선택) ━━━
1️⃣ 아침에 핸드폰 보면 / 뇌가 망가지는 이유
2️⃣ 기상 후 90분이 / 하루를 결정합니다
3️⃣ 아침루틴 하나로 / 인생이 바뀌는 과학적 이유

✅ 수정 없으면 무시하세요. 이미 1번으로 진행됩니다.
```

인라인 버튼:

```
[훅 변경]  [썸네일 문구 변경]  [제목 변경]
```

#### 훅 변경 플로우

```
사용자: [훅 변경] 버튼 탭
봇: "훅 번호를 선택하세요"
    [1] [2] [3] [4] [5]
사용자: [3] 탭
봇: "✅ 훅 #3 선택. 재생성 중..."
    → SSH로 로컬 PC 접속
    → yt-script: hook 교체 + tts_cleaner 재실행 + save
    → yt-production: TTS부터 재실행 (훅이 바뀌면 음성도 바뀜)
봇: "✅ 훅 변경 완료. yt-production 재실행이 필요합니다."
```

#### 썸네일 문구 변경 플로우

```
사용자: [썸네일 문구 변경] 버튼 탭
봇: "번호 선택 또는 직접 입력 (형식: line1 / line2)"
    [1] [2] [3]
사용자: [2] 탭  (또는 "아침 습관의 비밀 / 뇌과학이 증명한 루틴" 직접 입력)
봇: "✅ 썸네일 문구 #2 선택. 재생성 중..."
    → SSH: selected_text.json 저장
    → SSH: thumbnail/composer.py 재실행 (Pillow 합성만)
봇: "✅ 썸네일 재생성 완료"
    → [thumbnail.png 이미지 전송]
```

#### 제목 변경 플로우

```
사용자: [제목 변경] 버튼 탭
봇: "새 제목을 입력하세요. 현재: 아침 90분이 하루를 바꾼다"
사용자: "기상 후 90분의 비밀 — 뇌과학이 증명한 아침 루틴"
봇: "✅ 제목 변경 완료"
    → SSH: metadata.json의 title 필드 업데이트
```

### 3-2. 알림 2: yt-production 완료

봇이 보내는 메시지:

```
🎬 영상 완성 — YT-20260313-001

제목: 아침 90분이 하루를 바꾼다
롱폼: 13:00 | 10컷 | 1920x1080
숏폼: 4개 완성

[thumbnail.png 이미지 첨부]

업로드 준비 완료. 아래 버튼으로 업로드하세요.
```

인라인 버튼:

```
[🚀 지금 업로드]  [⏰ 예약 업로드]  [썸네일 변경]
```

#### 업로드 트리거 플로우

```
사용자: [🚀 지금 업로드] 탭
봇: "📤 업로드 시작..."
    → SSH: python run.py upload YT-20260313-001
봇: "✅ 업로드 완료!
     롱폼: https://youtube.com/watch?v=xxxxx
     숏폼 4개 업로드 완료"
```

#### 예약 업로드 플로우

```
사용자: [⏰ 예약 업로드] 탭
봇: "노출 시각을 입력하세요 (예: 내일 18시, 3/15 20:00)"
사용자: "내일 18시"
봇: "📅 2026-03-14 18:00 KST 예약 확인
     private으로 즉시 업로드 + 예약 공개됩니다."
    [확인] [취소]
사용자: [확인]
봇: "📤 업로드 중..."
    → SSH: python run.py upload YT-20260313-001 --publish-at "2026-03-14T18:00:00+09:00"
봇: "✅ 예약 업로드 완료! 2026-03-14 18:00 KST 공개 예정
     롱폼: https://youtube.com/watch?v=xxxxx"
```

#### 썸네일 변경 (production 완료 후)

```
사용자: [썸네일 변경] 탭
봇: "변경 방법을 선택하세요"
    [문구만 변경]  [이미지+문구 전체 재생성]
사용자: [문구만 변경]
    → (썸네일 문구 변경 플로우와 동일)
사용자: [이미지+문구 전체 재생성]
봇: "🔄 Whisk AI 이미지 + Pillow 합성 재실행 중..."
    → SSH: thumbnail/generator.py + composer.py 재실행
봇: "✅ 썸네일 전체 재생성 완료"
    → [새 thumbnail.png 이미지 전송]
```

---

## 4. 프로젝트 구조

```
yt-bot/
├── bot.py                      # 메인 진입점 (python-telegram-bot polling)
├── config.py                   # 환경변수, SSH 설정, 경로 설정
├── requirements.txt
├── .env
│
├── handlers/
│   ├── __init__.py
│   ├── script_complete.py      # 알림 1: yt-script 완료 핸들러
│   ├── production_complete.py  # 알림 2: yt-production 완료 핸들러
│   ├── hook.py                 # 훅 선택/변경 콜백
│   ├── thumbnail.py            # 썸네일 문구 선택/변경 콜백
│   ├── title.py                # 제목 확인/수정 콜백
│   ├── upload.py               # 업로드 트리거 + 예약 콜백
│   └── common.py               # 공통 유틸 (버튼 생성, 메시지 포맷 등)
│
├── services/
│   ├── __init__.py
│   ├── ssh.py                  # SSH 클라이언트 (paramiko)
│   ├── notifier.py             # Telegram 알림 발송 (파이프라인에서 호출용)
│   └── state.py                # 영상별 상태 관리 (SQLite)
│
├── notify/
│   ├── __init__.py
│   └── send.py                 # 파이프라인에서 import하여 사용하는 알림 모듈
│                                 (yt-script, yt-production에 복사 또는 pip 설치)
│
└── deploy/
    ├── setup_oracle.sh         # Oracle Cloud VM 초기 설정 스크립트
    ├── systemd/
    │   └── yt-bot.service      # systemd 서비스 파일
    └── ssh_keys/
        └── .gitkeep            # SSH 키 저장 위치 (.gitignore)
```

---

## 5. 핵심 모듈 상세

### 5-1. config.py

```python
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))       # 나의 chat_id (고정)

# SSH (로컬 PC 접속)
SSH_HOST = os.getenv("SSH_HOST")                     # 로컬 PC의 공인 IP 또는 DDNS
SSH_PORT = int(os.getenv("SSH_PORT", 22))
SSH_USER = os.getenv("SSH_USER")
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH", "deploy/ssh_keys/id_rsa")

# 로컬 PC 프로젝트 경로
LOCAL_YT_SCRIPT_DIR = os.getenv("LOCAL_YT_SCRIPT_DIR", "~/yt-script")
LOCAL_YT_PRODUCTION_DIR = os.getenv("LOCAL_YT_PRODUCTION_DIR", "~/yt-production")
LOCAL_YT_UPLOAD_DIR = os.getenv("LOCAL_YT_UPLOAD_DIR", "~/yt-upload")

# 상태 DB
DB_PATH = "state.db"
```

### 5-2. services/ssh.py

```python
"""
SSH로 로컬 PC에 접속하여 명령 실행.
paramiko 사용.
"""

import paramiko
from config import SSH_HOST, SSH_PORT, SSH_USER, SSH_KEY_PATH

class SSHClient:
    def __init__(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    def connect(self):
        self.client.connect(
            hostname=SSH_HOST,
            port=SSH_PORT,
            username=SSH_USER,
            key_filename=SSH_KEY_PATH,
        )
    
    def execute(self, command: str) -> tuple[str, str]:
        """명령 실행 후 (stdout, stderr) 반환"""
        self.connect()
        stdin, stdout, stderr = self.client.exec_command(command)
        out = stdout.read().decode()
        err = stderr.read().decode()
        self.client.close()
        return out, err
    
    def write_file(self, remote_path: str, content: str):
        """원격 파일 쓰기 (selected_text.json 등)"""
        self.connect()
        sftp = self.client.open_sftp()
        with sftp.open(remote_path, 'w') as f:
            f.write(content)
        sftp.close()
        self.client.close()
    
    def read_file(self, remote_path: str) -> str:
        """원격 파일 읽기"""
        self.connect()
        sftp = self.client.open_sftp()
        with sftp.open(remote_path, 'r') as f:
            content = f.read().decode()
        sftp.close()
        self.client.close()
        return content
    
    def download_file(self, remote_path: str, local_path: str):
        """원격 파일 다운로드 (썸네일 이미지 등)"""
        self.connect()
        sftp = self.client.open_sftp()
        sftp.get(remote_path, local_path)
        sftp.close()
        self.client.close()
```

### 5-3. services/notifier.py

파이프라인(yt-script, yt-production)에서 직접 호출하는 알림 모듈.
봇 서버를 거치지 않고 Telegram Bot API를 직접 호출.

```python
"""
파이프라인에서 사용하는 Telegram 알림 발송.
yt-bot 서버 없이도 동작 (Bot API 직접 호출).

사용법 (yt-script/yt-production에서):
    from notify.send import notify_script_complete, notify_production_complete
"""

import requests
import json
import os

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_message(text: str, reply_markup: dict = None):
    """텍스트 메시지 전송"""
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(f"{API_BASE}/sendMessage", json=payload)


def send_photo(photo_path: str, caption: str = "", reply_markup: dict = None):
    """이미지 + 캡션 전송"""
    payload = {"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    with open(photo_path, "rb") as f:
        requests.post(f"{API_BASE}/sendPhoto", data=payload, files={"photo": f})


def notify_script_complete(video_id: str, metadata: dict, output_dir: str):
    """
    yt-script 완료 알림 (알림 1)
    
    yt-script/nodes/save_outputs.py 마지막에 호출.
    """
    title = metadata.get("title", "제목 없음")
    total_chars = metadata.get("total_chars", 0)
    shorts_count = metadata.get("shorts_count", 0)
    
    # 훅 후보
    hook_candidates = metadata.get("hook_candidates", [])
    hook_text = "\n".join(
        f"{i+1}️⃣ {h}" for i, h in enumerate(hook_candidates)
    )
    
    # 썸네일 문구 후보
    thumb = metadata.get("thumbnail", {})
    thumb_candidates = thumb.get("text_candidates", [])
    thumb_text = "\n".join(
        f'{i+1}️⃣ {t["line1"]} / {t["line2"]}' for i, t in enumerate(thumb_candidates)
    )
    
    text = (
        f"📝 <b>대본 완성 — {video_id}</b>\n\n"
        f"제목: {title}\n"
        f"글자수: {total_chars:,}자 | 숏폼: {shorts_count}개\n\n"
        f"━━━ 훅 (현재: #1 자동선택) ━━━\n{hook_text}\n\n"
        f"━━━ 썸네일 문구 (현재: #1 자동선택) ━━━\n{thumb_text}\n\n"
        f"✅ 수정 없으면 무시하세요."
    )
    
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "훅 변경", "callback_data": f"hook_change:{video_id}"},
                {"text": "썸네일 문구 변경", "callback_data": f"thumb_change:{video_id}"},
                {"text": "제목 변경", "callback_data": f"title_change:{video_id}"},
            ]
        ]
    }
    
    send_message(text, reply_markup)


def notify_production_complete(video_id: str, metadata: dict, run_dir: str):
    """
    yt-production 완료 알림 (알림 2)
    
    yt-production/make_all.py 마지막에 호출.
    """
    title = metadata.get("title", "제목 없음")
    
    text = (
        f"🎬 <b>영상 완성 — {video_id}</b>\n\n"
        f"제목: {title}\n"
        f"업로드 준비 완료."
    )
    
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🚀 지금 업로드", "callback_data": f"upload_now:{video_id}"},
                {"text": "⏰ 예약 업로드", "callback_data": f"upload_schedule:{video_id}"},
            ],
            [
                {"text": "썸네일 변경", "callback_data": f"thumb_change_prod:{video_id}"},
            ]
        ]
    }
    
    # 썸네일 이미지 전송
    thumb_path = os.path.join(run_dir, "thumbnail", "thumbnail.png")
    if os.path.exists(thumb_path):
        send_photo(thumb_path, text, reply_markup)
    else:
        send_message(text, reply_markup)
```

### 5-4. services/state.py

```python
"""
영상별 상태 관리 (SQLite).
봇이 어떤 영상의 어떤 결정이 수정되었는지 추적.
"""

import sqlite3
from datetime import datetime

DB_PATH = "state.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            video_id TEXT,
            decision_type TEXT,
            original_value TEXT,
            modified_value TEXT,
            modified_at TEXT,
            PRIMARY KEY (video_id, decision_type)
        )
    """)
    conn.commit()
    conn.close()

def save_decision(video_id: str, decision_type: str, value: str):
    """결정 저장 (hook, thumbnail_text, title, publish_at)"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO decisions 
        (video_id, decision_type, modified_value, modified_at)
        VALUES (?, ?, ?, ?)
    """, (video_id, decision_type, value, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_decision(video_id: str, decision_type: str) -> str | None:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT modified_value FROM decisions WHERE video_id=? AND decision_type=?",
        (video_id, decision_type)
    ).fetchone()
    conn.close()
    return row[0] if row else None
```

### 5-5. handlers/thumbnail.py (예시)

```python
"""
썸네일 문구 선택/변경 콜백 핸들러
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters
from services.ssh import SSHClient
from services.state import save_decision
from config import LOCAL_YT_PRODUCTION_DIR
import json

ssh = SSHClient()

async def thumb_change_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """썸네일 문구 변경 버튼 콜백"""
    query = update.callback_query
    await query.answer()
    
    video_id = query.data.split(":")[1]
    context.user_data["pending_thumb_video_id"] = video_id
    
    # metadata에서 후보 목록 읽기
    metadata_path = f"{LOCAL_YT_PRODUCTION_DIR}/runs/{video_id}_script/metadata.json"
    metadata_str = ssh.read_file(metadata_path)
    metadata = json.loads(metadata_str)
    candidates = metadata.get("thumbnail", {}).get("text_candidates", [])
    
    buttons = []
    for i, c in enumerate(candidates):
        buttons.append([InlineKeyboardButton(
            f'{i+1}. {c["line1"]} / {c["line2"]}',
            callback_data=f"thumb_select:{video_id}:{i}"
        )])
    
    await query.edit_message_text(
        "썸네일 문구를 선택하세요.\n직접 입력: line1 / line2 형식으로 메시지 전송",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def thumb_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """번호 선택 콜백"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split(":")
    video_id = parts[1]
    index = int(parts[2])
    
    # metadata에서 선택된 문구 가져오기
    metadata_path = f"{LOCAL_YT_PRODUCTION_DIR}/runs/{video_id}_script/metadata.json"
    metadata_str = ssh.read_file(metadata_path)
    metadata = json.loads(metadata_str)
    selected = metadata["thumbnail"]["text_candidates"][index]
    
    await query.edit_message_text(f"✅ 썸네일 문구 #{index+1} 선택. 재생성 중...")
    
    # SSH: selected_text.json 저장
    selected_path = f"{LOCAL_YT_PRODUCTION_DIR}/runs/{video_id}_script/thumbnail/selected_text.json"
    ssh.write_file(selected_path, json.dumps(selected, ensure_ascii=False))
    
    # SSH: Pillow 합성 재실행
    cmd = (
        f"cd {LOCAL_YT_PRODUCTION_DIR} && "
        f"python -m thumbnail.composer "
        f"--bg runs/{video_id}_script/thumbnail/thumb_bg.png "
        f"--text runs/{video_id}_script/thumbnail/selected_text.json "
        f"--output runs/{video_id}_script/thumbnail/thumbnail.png"
    )
    out, err = ssh.execute(cmd)
    
    # 상태 저장
    save_decision(video_id, "thumbnail_text", json.dumps(selected, ensure_ascii=False))
    
    # 새 썸네일 전송
    local_tmp = f"/tmp/{video_id}_thumb.png"
    remote_thumb = f"{LOCAL_YT_PRODUCTION_DIR}/runs/{video_id}_script/thumbnail/thumbnail.png"
    ssh.download_file(remote_thumb, local_tmp)
    
    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=open(local_tmp, "rb"),
        caption="✅ 썸네일 재생성 완료"
    )

async def thumb_direct_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """직접 입력 처리 (line1 / line2 형식)"""
    video_id = context.user_data.get("pending_thumb_video_id")
    if not video_id:
        return
    
    text = update.message.text
    if "/" not in text:
        await update.message.reply_text("형식: line1 / line2")
        return
    
    parts = text.split("/", 1)
    selected = {"line1": parts[0].strip(), "line2": parts[1].strip()}
    
    await update.message.reply_text(f"✅ 직접 입력 확인. 재생성 중...")
    
    # (위 thumb_select_callback과 동일한 SSH 로직)
    # ...
    
    context.user_data.pop("pending_thumb_video_id", None)
```

---

## 6. SSH 설정

### 로컬 PC 준비

```bash
# 1. SSH 서버 활성화 (macOS)
sudo systemsetuid -setremotelogin on

# 2. SSH 키 생성 (Oracle Cloud VM에서)
ssh-keygen -t ed25519 -f ~/.ssh/yt-bot-key -N ""

# 3. 공개키를 로컬 PC에 등록
# Oracle VM의 ~/.ssh/yt-bot-key.pub 내용을
# 로컬 PC의 ~/.ssh/authorized_keys에 추가

# 4. 로컬 PC 공인 IP 확인 (또는 DDNS 설정)
curl ifconfig.me
```

### 보안 고려사항

- SSH 키 인증만 허용 (비밀번호 인증 비활성화)
- 로컬 PC 방화벽에서 SSH 포트는 Oracle Cloud VM IP만 허용
- SSH 키는 `.gitignore`에 추가
- 봇의 SSH 사용자에게 최소 권한 부여 (yt-* 디렉토리만 접근 가능)
- 로컬 PC가 절전 모드면 SSH 접속 불가 → Wake on LAN 또는 절전 비활성화

### DDNS 추천 (가정용 IP 변동 대응)

로컬 PC의 공인 IP가 변할 수 있으므로 DDNS 설정 추천:
- Duck DNS (무료)
- No-IP (무료 플랜)
- .env의 SSH_HOST에 DDNS 도메인 사용

---

## 7. Oracle Cloud 배포

### VM 스펙 (Free Tier)

- Shape: VM.Standard.A1.Flex (ARM)
- OCPU: 1
- RAM: 6GB (Free Tier 최대)
- Storage: 50GB
- OS: Ubuntu 22.04

### 초기 설정

```bash
# deploy/setup_oracle.sh

#!/bin/bash
set -e

# 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# Python 3.11+
sudo apt install -y python3.11 python3.11-venv python3-pip

# 프로젝트 클론
cd ~
git clone https://github.com/{user}/yt-bot.git
cd yt-bot

# 가상환경
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# .env 설정
cp .env.example .env
nano .env  # BOT_TOKEN, CHAT_ID, SSH 설정 입력

# SSH 키 배치
mkdir -p deploy/ssh_keys
# (로컬 PC 접속용 비밀키를 여기에 복사)

# systemd 서비스 등록
sudo cp deploy/systemd/yt-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable yt-bot
sudo systemctl start yt-bot
```

### systemd 서비스 파일

```ini
# deploy/systemd/yt-bot.service

[Unit]
Description=yt-bot Telegram Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/yt-bot
ExecStart=/home/ubuntu/yt-bot/.venv/bin/python bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

### 방화벽 설정

Oracle Cloud의 VCN Security List:
- 인바운드: 불필요 (봇은 polling 방식, 외부 접속 없음)
- 아웃바운드: 전체 허용 (Telegram API + SSH to 로컬)

---

## 8. 파이프라인 연동 방법

### yt-script 연동

`nodes/save_outputs.py` 마지막에 추가:

```python
# save_outputs.py 수정 (기존 저장 로직 뒤에 추가)

try:
    from notify.send import notify_script_complete
    notify_script_complete(
        video_id=state["video_id"],
        metadata=metadata,
        output_dir=output_dir,
    )
except Exception as e:
    print(f"[WARN] Telegram 알림 실패 (무시): {e}")
```

### yt-production 연동

`make_all.py` 마지막에 추가:

```python
# make_all.py 수정 (영상 합성 완료 후 추가)

try:
    from notify.send import notify_production_complete
    notify_production_complete(
        video_id=video_id,
        metadata=metadata,
        run_dir=run_dir,
    )
except Exception as e:
    print(f"[WARN] Telegram 알림 실패 (무시): {e}")
```

### notify 모듈 배포 방법

```bash
# 방법 1: 심볼릭 링크 (추천)
ln -s ~/yt-bot/notify ~/yt-script/notify
ln -s ~/yt-bot/notify ~/yt-production/notify

# 방법 2: pip 설치 (나중에)
# yt-bot을 패키지로 만들어서 pip install -e .
```

### .env 추가 (yt-script, yt-production)

```env
# Telegram 알림 (yt-bot)
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=1234567890
```

---

## 9. 개입 지점별 SSH 명령어 매핑

| 개입 지점 | 봇 액션 | SSH 명령 |
|----------|---------|---------|
| 훅 변경 | metadata.json 수정 + script 재생성 | `cd ~/yt-script && python run.py rehook {video_id} --hook-index {N}` |
| 썸네일 문구 변경 | selected_text.json 저장 + Pillow 재실행 | `cd ~/yt-production && python -m thumbnail.composer --run-dir runs/{video_id}_script/` |
| 썸네일 전체 재생성 | Whisk AI + Pillow | `cd ~/yt-production && python -m thumbnail.generator --run-dir runs/{video_id}_script/ && python -m thumbnail.composer --run-dir runs/{video_id}_script/` |
| 제목 변경 | metadata.json의 title 수정 | SFTP로 metadata.json 직접 수정 |
| 업로드 (즉시) | yt-upload 실행 | `cd ~/yt-upload && python run.py upload {video_id}` |
| 업로드 (예약) | yt-upload 실행 + publish_at | `cd ~/yt-upload && python run.py upload {video_id} --publish-at "{datetime}"` |

---

## 10. 엣지 케이스 처리

| 케이스 | 처리 |
|--------|------|
| SSH 접속 실패 (로컬 PC 꺼짐/절전) | "⚠️ 로컬 PC에 접속할 수 없습니다. PC가 켜져 있는지 확인하세요." 메시지 |
| SSH 명령 실행 실패 | stderr 내용을 Telegram으로 전송 + "수동 확인 필요" 안내 |
| 내가 아닌 사람이 봇에 메시지 보냄 | chat_id 체크 → 무시 (응답 없음) |
| 이미 업로드된 영상에 다시 업로드 시도 | upload_package.json의 youtube_video_id 체크 → "이미 업로드됨" 안내 |
| Telegram Bot API 장애 | 파이프라인은 정상 완료 (알림만 실패). try-except로 처리 |
| 썸네일 재생성 중 Whisk AI 실패 | SSH stderr 전송 + "수동 제작 필요" 안내 |
| 로컬 PC IP 변경 (DDNS 미설정) | SSH 실패 → DDNS 설정 안내 메시지 |
| 봇 서버 재시작 | systemd가 자동 재시작. SQLite 상태 유지 |

---

## 11. .env.example

```env
# Telegram Bot
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=1234567890

# SSH (로컬 PC 접속)
SSH_HOST=mypc.duckdns.org          # 또는 공인 IP
SSH_PORT=22
SSH_USER=jaesun
SSH_KEY_PATH=deploy/ssh_keys/id_ed25519

# 로컬 PC 프로젝트 경로
LOCAL_YT_SCRIPT_DIR=/Users/jaesun/yt-script
LOCAL_YT_PRODUCTION_DIR=/Users/jaesun/yt-production
LOCAL_YT_UPLOAD_DIR=/Users/jaesun/yt-upload
```

---

## 12. 의존성

```
# requirements.txt

python-telegram-bot>=21.0
paramiko>=3.4
python-dotenv>=1.0
```

봇 자체는 경량. python-telegram-bot(Telegram 통신) + paramiko(SSH) + dotenv(설정) 3개면 충분.
FastAPI는 불필요 (파이프라인이 봇 API를 호출할 필요 없으므로).
