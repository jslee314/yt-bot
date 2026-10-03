"""입력 검증 — telegram 의존 없음(테스트에서 바로 import 한다).

video_id는 callback_data와 사용자 메시지에서 와서 shell=True 명령과 파일 경로에
그대로 들어간다. 버튼을 봇이 만들었다는 사실은 보증이 되지 않는다 — MTProto
클라이언트는 임의의 64바이트를 callback_data로 보낼 수 있다.
"""
import re

# config.CHANNELS[*]["id_re"] 와 같은 기준 + 숏폼 접미사.
# fullmatch 를 쓴다 — match 는 "YT-…-004\nwhoami" 처럼 개행 뒤 내용을 통과시킨다.
_VIDEO_ID_RE = re.compile(r"YT-\d{8}-\d{3}(?:-JA)?(?:-S\d{2})?")


def valid_video_id(video_id) -> bool:
    return isinstance(video_id, str) and bool(_VIDEO_ID_RE.fullmatch(video_id))
