"""/help — 봇 사용법을 텔레그램 안에서 본다.

  /help          개요: 명령 한 줄씩 + 자동 알림 + 주제 목록
  /help <주제>   자세히 — 명령 · 채널 · 알림 · link · run · stuck · 실험
  /help pin      개요를 채팅 상단에 고정 (언제든 다시 보게)

설명서를 코드 옆에 두는 이유: 명령이 바뀌면 설명도 같은 커밋에서 바뀐다.
README 는 컴퓨터에서나 보지만, 이 봇은 폰에서 쓴다.
"""

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from handlers.common import auth_check

logger = logging.getLogger(__name__)

OVERVIEW = """🤖 <b>yt-bot 사용법</b>

유튜브 자동화 파이프라인을 폰에서 보고 조작합니다. 채널 두 개를 한 봇이 봅니다:
🇰🇷 <code>ko</code> 괜찮아연구소 (기본)  ·  🇯🇵 <code>ja</code> 大丈夫研究所

<b>보기</b>
/status — 지금 상태 한 장 (실행 중? 마지막 성공? 큐? 다음 대상?)
/queue — 남은 작업 목록
/log — 최근 실행 로그 40줄 (<code>/log 100</code>)
/stuck — 올라갔는데 공개 안 된 영상 점검

<b>조작</b>
/run — 지금 제작·업로드 (10일 간격 적용)
<code>/run ko force</code> — 간격 무시 ⚠️ 크레딧 소모
/stop — 실행 중단
/link — 숏폼에 롱폼 '관련 동영상' 걸 링크 묶음

채널을 붙이면 그 채널: <code>/status ja</code> <code>/stuck ja</code> <code>/link ja</code>

<b>자동으로 오는 알림</b>  (지금은 🇰🇷 KO만)
🎬 시작 · ✅ 완료(유튜브 링크+공개 예약) · ❌ 실패(단계+로그 40줄)
평소엔 아무것도 안 해도 됩니다. ❌가 오면 /log → 고치고 /run.

<b>자세히</b>  /help 명령 · /help 채널 · /help 알림 · /help link · /help run · /help stuck · /help 실험
<b>상단 고정</b>  /help pin"""

TOPICS = {
    "명령": """📖 <b>명령 자세히</b>

<b>/status</b> [ko|ja]
실행 중(🟢) · 마지막 성공(⚪️, 3일 넘으면 🔴 경고) · 최근 실행 판정(✅ ❌ ⏭) · 큐 · 다음 대상 · 간격 잔여.
채널 없이 치면 KO 전체 + JA 요약.

<b>/queue</b> [ko|ja]
미업로드 대본을 파이프라인이 집는 순서(오래된 것부터)로 15개까지.

<b>/log</b> [ko|ja] [줄수]
최근 실행 로그 꼬리 (기본 40, 최대 200). ❌ 알림이 오면 제일 먼저 볼 것.

<b>/run</b> [ko|ja] [force]
auto_pipeline.sh를 띄웁니다 — 세션과 분리돼 봇이 죽어도 계속 돕니다.
제작 → 메타데이터 → 공개 예약 → 업로드. 이미 만든 영상이 있으면 제작은 건너뜁니다. /help run

<b>/stop</b>
실행 중인 파이프라인에 중단 신호. 이미 쓴 TTS·이미지 비용은 환불되지 않습니다.

<b>/stuck</b> [ko|ja]
채널 전체를 훑어 private·예약없음 영상을 나열. /help stuck

<b>/link</b> [ko|ja|all] · <code>/link YT-…</code> · <code>/link done YT-…</code>
숏폼마다 Studio 편집 링크. 끝낸 세트는 done으로 숨김. /help link""",

    "채널": """🌏 <b>채널</b>

🇰🇷 <code>ko</code> <b>괜찮아연구소</b> — 기본. 채널을 생략하면 이것.
자동 파이프라인 있음(매일 03:00 launchd, 10일 간격) · 알림 옴 · /run 됨.

🇯🇵 <code>ja</code> <b>大丈夫研究所</b> — 일본 미러. 한국판 <b>이미지를 재사용</b>하고 음성·자막만 일본어로 다시 만듭니다 (이미지가 비용의 절반이라 추가 비용이 거의 없음).
<b>반자동</b>: 터미널에서 <code>MARKET=ja bash mirror_build.sh &lt;ID&gt;</code> 로 제작 → 업로드는 수동.
그래서 <b>/run ja 는 아직 거부</b>하고 <b>알림도 안 옵니다</b>. /status ja · /queue ja · /stuck ja · /link ja 는 됩니다.

<b>계정 셋 — 섞이면 안 됩니다</b>
· KO 채널: <code>jaeseonlee.0314@</code>
· JA 채널: <code>jaeseonlee314@</code>
· GCP 콘솔(프로젝트 주인): <code>jaeseon314@</code>
토큰은 "동의한 계정의 채널"을 가리킵니다. /link 의 Studio 링크는 그 채널 계정으로 로그인돼 있어야 열립니다.

<b>쿼터</b> 채널마다 GCP 프로젝트가 따로(<code>yt-upload</code> / <code>yt-upload-ja</code>)라 하루 10,000 unit씩. 세트 하나 업로드 ≈ 9,650 → 채널당 하루 한 세트.
<b>TTS 크레딧</b>은 ElevenLabs 계정 하나를 공유 → 10일 간격은 두 채널 합산으로.""",

    "알림": """🔔 <b>알림 읽는 법</b>

맨 앞 🇰🇷/🇯🇵 — 어느 채널 일인지.
<b>지금은 KO만 알림이 옵니다.</b> JA는 반자동(mirror_build.sh)이라 알림 연결 전 — 진행은 /status ja 로 봅니다.

🎬 <b>파이프라인 시작</b> — 대상 ID. 1~3시간 걸립니다.

✅ <b>업로드 완료</b> — 롱폼·숏폼 유튜브 링크와 공개 예약 시각.
private로 올라가 예약 시각(롱폼 당일 19:00, 숏폼 08:00/19:00 번갈아)에 자동 공개됩니다.
→ 링크 눌러 확인. 맘에 안 들면 공개 전에 Studio에서 수정.
→ 그다음 /link 로 숏폼에 관련 동영상 걸기 — 유일한 수동 단계.

❌ <b>파이프라인 실패</b> — 어느 단계인지 + 로그 40줄.
→ /log 로 원인 → 고친 뒤 /run.
이미 만든 TTS·이미지는 남아 있어 재실행 때 재사용됩니다 (yt-pipeline/resume_build.sh).

알림이 아예 안 오면 /status 를 보세요. 마지막 성공이 🔴면 뭔가 멈춘 것입니다. 2026년 5~10월엔 cron이 조용히 죽어 5개월간 아무도 몰랐습니다 — 그래서 알림과 🔴 경고가 생겼습니다.""",

    "link": """🔗 <b>숏폼 → 롱폼 '관련 동영상' 걸기</b>

<b>왜</b> 유입의 92%가 Shorts 피드인데 숏폼에서 롱폼으로 건너갈 문이 없었습니다. 설명란 URL은 아무도 안 누릅니다. '관련 동영상'은 화면에 버튼으로 뜹니다. Data API에 필드가 없어 <b>Studio에서 손으로만</b> 됩니다.

<b>절차</b> (숏폼 1개당 20초)
1. /link (JA는 /link ja) → 세트별로 숏폼 편집 링크가 옵니다
2. 링크 → Studio 편집 화면 → 오른쪽 <b>관련 동영상</b> → 아래 적힌 롱폼 선택 → 저장
3. 세트가 끝나면 <code>/link done YT-…</code> → 목록에서 사라집니다

<b>조건</b> 채널에 고급 기능 액세스 (Studio → 설정 → 채널 → 기능 사용 자격요건). 대상 롱폼은 공개/미등록.
<b>주의</b> 링크는 그 채널 계정으로 로그인된 Studio에서만 열립니다 (/help 채널).

<b>우선순위 — 전부 할 필요 없습니다</b>
이미 공개된 옛 숏폼은 조회가 0에 수렴해 효과가 없습니다. <b>앞으로 공개될 것만</b>:
· KO 15개 — 10/04 08:00 ~ 10/09 08:00 공개
· JA 4개 — 10/04 19:00 ~ 10/06 08:00 공개 (롱폼은 10/04 08:00)""",

    "run": """▶️ <b>/run 과 10일 간격</b>

매일 03:00 launchd가 깨우지만(자고 있었으면 깨어날 때) 실제 제작은 <b>마지막 성공 후 10일</b>이 지났을 때만 합니다. 10일 = 월 3편.

<b>근거</b> 롱폼 1편 TTS ≈ 6,000자, ElevenLabs Starter 월 40,000자. 하루 1편이면 7일째 크레딧이 바닥납니다. (실측은 세트당 ~2,350이라 간격을 당길 여지가 있음 — 확인 중)

<code>/run</code> — 간격이 안 찼으면 거부하고 남은 시간을 알려줍니다.
<code>/run ko force</code> — 간격 무시. 월 한도를 일찍 소진합니다. 급한 1편에만.
<code>/run ja</code> — 아직 거부. JA는 터미널에서 <code>MARKET=ja bash mirror_build.sh &lt;ID&gt;</code>.

실행은 세션과 분리돼 봇이 죽어도 계속 돕니다. 진행은 /log, 끝나면 ✅/❌ 알림.
한 세트 = 롱폼 1 + 숏폼 4~5 · 비용 ≈ 6,300원 · 1~3시간 · Data API ≈ 9,650 unit (하루 10,000).
JA 미러는 이미지를 재사용해 TTS만 — 실측 2,957 크레딧, 이미지 0원.""",

    "stuck": """🩺 <b>/stuck — 올라갔는데 공개 안 된 영상</b>

업로드가 성공하면 파이프라인은 '성공'으로 기록하고 끝납니다. 그 뒤 공개 예약을 못 받아 private로 남아도 아무 데도 안 남습니다. 실제로 <b>숏폼 11개가 5개월간</b> 그렇게 묻혀 있었습니다 (2026-10-03 발견 → 분산 예약으로 구조).

<code>/stuck</code> — KO 채널 전체를 훑어 private·예약없음 영상을 나열. (현재 0개)
<code>/stuck ja</code> — JA 채널. (미러 전환 전 옛 영상 60개가 전부 private — 의도된 상태. 새로 올린 5개는 예약이 있어 안 잡힘)

뜨면: Studio에서 공개하거나, Claude에 "분산 예약" 요청. 가끔 한 번씩 눌러 보세요.
YouTube API 조회라 몇 초 걸립니다.""",

    "실험": """🧪 <b>실험 A·C (2026-10-03 시작)</b>

<b>진단</b> 롱폼 CTR 4.2%·0~30초 유지율 76%는 정상 — 노출만 없음. 롱폼 유입은 Shorts가 아니라 <b>검색</b>(휴면기 85%). 100회 넘긴 롱폼 3편은 전부 검색·탐색으로.

<b>A 숏폼→롱폼 다리</b> 공개 예정 숏폼 19개(KO 15 + JA 4)에 관련 동영상 걸기 (/link).
판정(2주): 롱폼의 Shorts 유입 <b>절대 조회</b>. 기준선 0 (2~3월엔 편당 ~4였다가 4월부터 0).

<b>C 검색 수요형 제목</b> 백로그 3편(-010/-017/-029) 제목·썸네일을 사람들이 치는 질문형으로. 제작은 대상 지정 들어간 뒤.
판정(4주): 공개 후 14일 검색+탐색 조회. 기존 중앙값 <b>4회</b> · ≥48이면 분명한 신호 · 3편 중 2편이면 C 확정.

둘 다 A/B가 아니라 <b>전후 비교 파일럿</b> — 큰 효과만 봅니다. 애매하면 다음 20편 홀짝 교차 배치로.
측정은 터미널: <code>cd ~/Projects/yt-pipeline && python3 tools/traffic_baseline.py --per-video</code>""",
}

# 영문·다른 표기도 같은 주제로
ALIASES = {
    "commands": "명령", "명령어": "명령", "cmd": "명령",
    "channel": "채널", "channels": "채널",
    "notify": "알림", "notification": "알림", "알림들": "알림",
    "링크": "link", "관련": "link",
    "실행": "run", "간격": "run",
    "방치": "stuck", "미공개": "stuck",
    "experiment": "실험", "ab": "실험", "a": "실험", "c": "실험",
}


def topic_text(name: str) -> str | None:
    key = ALIASES.get(name.lower(), name)
    return TOPICS.get(key)


@auth_check
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = list(context.args or [])
    if not args:
        await update.message.reply_text(OVERVIEW, parse_mode="HTML", disable_web_page_preview=True)
        return

    if args[0].lower() in ("pin", "고정"):
        msg = await update.message.reply_text(OVERVIEW, parse_mode="HTML", disable_web_page_preview=True)
        try:
            await context.bot.pin_chat_message(
                chat_id=update.effective_chat.id, message_id=msg.message_id, disable_notification=True
            )
        except Exception as e:  # noqa: BLE001 — 고정 실패는 치명적이지 않다
            logger.warning("pin failed: %s", e)
            await update.message.reply_text(f"고정은 실패했습니다 ({e}). 메시지는 위에 있습니다.")
        return

    text = topic_text(args[0])
    if text is None:
        await update.message.reply_text(
            f"'{args[0]}' 주제는 없습니다.\n"
            f"가능: {' · '.join(TOPICS)}  (예: <code>/help link</code>)",
            parse_mode="HTML",
        )
        return
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


def register(app: Application):
    # Telegram 명령은 소문자 영문·숫자·밑줄만 허용한다 — 한글 별칭을 넣으면 기동 시
    # CommandHandler 가 ValueError 를 던져 봇이 재시작 루프에 빠진다 (2026-10-03 실측).
    app.add_handler(CommandHandler(["help", "start"], cmd_help))
