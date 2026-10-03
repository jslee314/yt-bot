# yt-bot

YouTube 자동화 파이프라인(yt-script → yt-production_whisk → yt-upload)의
**모바일 모니터링 + 조작** 텔레그램 봇.

파이프라인은 1번 후보로 끝까지 자동 완주하고, 봇은 결과를 알려준 뒤
수정이 필요하면 처리한다.

## 아키텍처

봇은 **파이프라인과 같은 맥에서** 돈다. 롱폴링이라 맥에서 바깥으로 나가는
연결만 쓰므로 포트 개방·DDNS·클라우드 VM이 전부 불필요하다.

```
[맥 (집)]                                      [Telegram]

launchd ──03:00── yt-pipeline/auto_pipeline.sh
  (자고 있었으면            │
   깨어날 때 실행)          ├─ 시작/성공/실패 ──→ 📱 알림
                            │   (notify.sh, curl)
                            ├─ yt-production_whisk
                            └─ yt-upload

launchd ─상주─ yt-bot (롱폴링) ←────────────── 📱 /status /run /log
                            │                       /queue /stop
                            └─ 로컬 subprocess 실행
```

초기 설계는 Oracle Cloud에 봇을 올리고 SSH로 맥에 역접속하는 구조였으나,
폴링 봇에 SSH를 붙일 이유가 없고 집 맥에 22번 포트를 여는 건 순수 리스크
추가여서 폐기했다. `services/ssh.py`(paramiko)는 동일 인터페이스의
`services/runner.py`(로컬 subprocess)로 교체됐고 핸들러는 그대로 쓴다.

## 설치

```bash
bash deploy/install_local.sh
```

`.env`가 없으면 만드는 방법을 안내하고 멈춘다. 필요한 건 두 값뿐이다.

| 값 | 얻는 방법 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | 텔레그램에서 `@BotFather` → `/newbot` |
| `TELEGRAM_CHAT_ID` | 봇에게 메시지 하나 보낸 뒤 `getUpdates`로 확인 (`.env.example` 참고) |

설치 스크립트는 토큰 유효성과 `chat_id` 도달 가능 여부까지 실제로 검증한 뒤
launchd에 등록한다.

## 명령

채널(`ko` 괜찮아연구소 / `ja` 今日もこんなふうに)은 첫 인자로 고른다. 생략하면 `ko`.
사용법 전문은 봇 안에서 `/help` 로 본다 — `handlers/help.py` 가 단일 출처다.

| 명령 | 동작 |
|---|---|
| `/status [ch]` | 모든 채널 한 장(ko 전체 + 나머지 요약). 마지막 성공, 최근 판정, 큐, 다음 대상, 간격 잔여 |
| `/queue [ch]` | 미업로드 작업 목록 (파이프라인이 집는 순서) |
| `/run [ch] [force]` | 지금 실행 (10일 간격 적용). `force` 는 간격 무시 — 크레딧 소모 주의 |
| `/log [ch] [줄수]` | 최근 실행 로그 tail (기본 40줄) |
| `/stop` | 실행 중인 파이프라인 중단 |
| `/stuck [ch]` | 채널에서 올라갔지만 공개도 예약도 안 된 영상 찾기 (채널 토큰으로 조회) |
| `/link [ch\|all]` | 숏폼마다 롱폼 '관련 동영상'을 걸 Studio 편집 링크. `/link done <id>` 로 세트 완료 기록 |
| `/help [주제\|pin]` | 사용법. 주제: 명령·채널·알림·link·run·stuck·실험. `pin` 은 개요를 상단 고정 |

`/status`는 마지막 성공이 `STALE_WARN_DAYS`(기본 3일)를 넘기면 경고를 띄운다.
**알림이 없어 조용히 죽은 걸 모르는 상황**을 막는 장치다. 실행 간격은 `auto_pipeline.sh`
의 `MIN_INTERVAL` 을 읽어 온다 — 숫자를 복제하지 않는다.

`/run ja` 는 `config.CHANNELS["ja"]["orchestrated"]` 가 `True` 가 될 때까지 거부한다
(`auto_pipeline.sh` 에 `CHANNEL` 매개변수가 들어오면 바꾼다).

## 개입 지점 (파이프라인 알림에 붙는 버튼)

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
├── bot.py                      # 진입점 (롱폴링, 명령 메뉴 등록)
├── config.py                   # 환경변수, 경로, PYTHON_BIN
├── services/
│   ├── runner.py               # 로컬 실행기 (execute/spawn/read/write)
│   ├── pipeline.py             # 파이프라인 상태 조회 (단일 진실 공급원)
│   └── state.py                # 결정 이력 (SQLite)
├── handlers/
│   ├── commands.py             # /status /queue /run /log /stop /stuck /link (채널 인자)
│   ├── help.py                 # /help — 주제별 설명서, /help pin
│   ├── script_complete.py      # 알림 1 (훅·썸네일·제목)
│   ├── production_complete.py  # 알림 2 (업로드·예약)
│   ├── hook.py / thumbnail.py / title.py / upload.py
│   └── common.py               # chat_id 인증, 에러 응답
├── notify/send.py              # 파이프라인에서 쓰는 알림 발송 (봇 없이도 동작)
└── deploy/
    ├── install_local.sh        # 설치 (검증 → launchd 등록)
    └── com.jslee.yt-bot.plist  # 상주 설정
```

## 관련 파일 (yt-bot 밖)

오케스트레이터는 별도 저장소 [yt-pipeline](../yt-pipeline)에 있다.

| 경로 | 역할 |
|---|---|
| `../yt-pipeline/auto_pipeline.sh` | 파이프라인 오케스트레이터. 단계별 알림 훅 포함 |
| `../yt-pipeline/notify.sh` | 쉘용 알림 헬퍼 (curl만 사용, 봇 없이 동작) |
| `../yt-pipeline/deploy/install.sh` | 파이프라인 스케줄 등록 (cron 대체) |
| `../yt-pipeline/logs/` | 실행 로그 — `/status`와 `/log`가 읽는다 |

### cron을 쓰지 않는 이유

맥이 03:00에 자고 있으면 cron은 그 실행을 **영구히 건너뛴다.**
실제로 `crontab(0 3 * * *)`과 `pmset` 기상 시각(05:55)이 어긋나
2026-05-19 이후 약 5개월간 파이프라인이 한 번도 돌지 않았고,
알림이 없어 아무도 몰랐다. launchd는 `StartCalendarInterval`을 놓치면
**깨어날 때 실행**한다. 또 파이프라인이 수십 분~수 시간 걸리므로
`caffeinate -i`로 감싸 유휴 절전이 중간에 끼어들지 못하게 한다.
