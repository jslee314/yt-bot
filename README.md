# yt-bot

YouTube 자동화 파이프라인(yt-script, yt-production, yt-upload)의 **사후 승인/수정 Telegram 봇**.

파이프라인은 항상 1번 후보로 끝까지 자동 완주하고, 봇은 결과를 알려준 뒤 수정이 필요하면 처리한다.

## 아키텍처

```
[로컬 PC]                        [Oracle Cloud]           [Telegram]
                                  yt-bot 서버
파이프라인 완료                    (python-telegram-bot
  → Telegram Bot API               + paramiko SSH)  ──→  📱 알림
    직접 호출 (HTTP) ──────────→                            │
                                                            ↓
                                                        사용자 응답
                                                            │
                                  봇이 callback 처리  ←─────┘
                                    ↓
                                  SSH로 로컬 PC 접속
                                    → 해당 스텝만 재실행
```

## 개입 지점

| # | 개입 지점 | 타이밍 |
|---|----------|--------|
| 1 | 훅 선택 | yt-script 완료 후 |
| 2 | 썸네일 문구 선택 | yt-script 완료 후 |
| 3 | 제목 확인/수정 | yt-script 완료 후 |
| 4 | 업로드 트리거 | yt-production 완료 후 |
| 5 | 노출 시각 지정 | 업로드 트리거 시 |

## 프로젝트 구조

```
yt-bot/
├── bot.py                      # 메인 진입점 (polling)
├── config.py                   # 환경변수, SSH/경로 설정
├── requirements.txt
├── handlers/
│   ├── common.py               # 인증 체크, 에러 핸들링
│   ├── hook.py                 # 훅 선택/변경
│   ├── thumbnail.py            # 썸네일 문구/이미지 변경
│   ├── title.py                # 제목 수정
│   ├── upload.py               # 업로드 (즉시/예약)
│   ├── script_complete.py      # 알림1 핸들러 등록
│   └── production_complete.py  # 알림2 핸들러 등록
├── services/
│   ├── ssh.py                  # SSH 클라이언트 (paramiko)
│   ├── state.py                # SQLite 상태 관리
│   └── notifier.py             # 알림 발송
├── notify/
│   └── send.py                 # 파이프라인에서 import하는 알림 모듈
└── deploy/
    ├── setup_oracle.sh         # Oracle Cloud VM 초기 설정
    └── systemd/
        └── yt-bot.service      # systemd 서비스 파일
```

## 설정

```bash
cp .env.example .env
# .env 파일에 실제 값 입력
pip install -r requirements.txt
python bot.py
```

### 환경변수

| 변수 | 설명 |
|------|------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API 토큰 |
| `TELEGRAM_CHAT_ID` | 사용자 chat_id (고정) |
| `SSH_HOST` | 로컬 PC 공인 IP 또는 DDNS |
| `SSH_PORT` | SSH 포트 (기본 22) |
| `SSH_USER` | SSH 사용자명 |
| `SSH_KEY_PATH` | SSH 비밀키 경로 |
| `LOCAL_YT_SCRIPT_DIR` | 로컬 yt-script 경로 |
| `LOCAL_YT_PRODUCTION_DIR` | 로컬 yt-production 경로 |
| `LOCAL_YT_UPLOAD_DIR` | 로컬 yt-upload 경로 |

## 파이프라인 연동

```bash
# notify 모듈 심볼릭 링크
ln -s ~/yt-bot/notify ~/yt-script/notify
ln -s ~/yt-bot/notify ~/yt-production/notify
```

파이프라인 코드 마지막에 추가:

```python
# yt-script
from notify.send import notify_script_complete
notify_script_complete(video_id, metadata, output_dir)

# yt-production
from notify.send import notify_production_complete
notify_production_complete(video_id, metadata, run_dir)
```

## 배포 (Oracle Cloud)

```bash
bash deploy/setup_oracle.sh
```

의존성: `python-telegram-bot`, `paramiko`, `python-dotenv`
