"""/schedule — 공개 일정 집계.

핵심: 업로드만 하고 publish_at 을 빼먹으면 private 로 묻힌다(한국 숏폼 11개가 5개월).
다만 publish_at 필드는 2026-05-04에 생겼으므로, 그 전 업로드까지 경고하면
거짓 경보가 80건 난다 — '최근 패키지'만 위험으로 센다.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import services.pipeline as P  # noqa: E402

KST = timezone(timedelta(hours=9))


def _pkg(d: Path, vid: str, *, longform_at, shorts_at, mtime_days_ago=0):
    out = d / vid
    out.mkdir(parents=True, exist_ok=True)
    data = {
        "video_id": vid,
        "longform": {"title": "롱폼제목", "youtube_video_id": "L" + vid[-3:],
                     **({"publish_at": longform_at} if longform_at else {})},
        "shorts": [{"shorts_id": f"{vid}-S0{i}", "title": f"숏폼{i}",
                    "youtube_video_id": f"S{i}{vid[-3:]}",
                    **({"publish_at": shorts_at} if shorts_at else {})}
                   for i in range(1, 3)],
    }
    f = out / "upload_package.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    if mtime_days_ago:
        past = time.time() - mtime_days_ago * 86400
        os.utime(f, (past, past))
    return f


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_upload_outputs", lambda: tmp_path)
    return tmp_path


def _utc_in(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_예약된_것을_시간순으로_모은다(uploads):
    _pkg(uploads, "YT-20260501-001", longform_at=_utc_in(30), shorts_at=_utc_in(10))
    items = P.scheduled_items("ko")
    assert len(items) == 3
    assert all(i.publish_at is not None for i in items)


def test_최근_업로드의_예약누락은_경고한다(uploads):
    _pkg(uploads, "YT-20260501-002", longform_at=None, shorts_at=None)
    rep = P.schedule_report(["ko"])
    assert "예약이 없는 영상 3개" in rep


def test_옛_업로드의_예약누락은_경고하지_않는다(uploads):
    """publish_at 도입(2026-05-04) 이전 업로드 — 이미 공개돼 있다."""
    _pkg(uploads, "YT-20260401-001", longform_at=None, shorts_at=None, mtime_days_ago=120)
    rep = P.schedule_report(["ko"])
    assert "예약이 없는 영상" not in rep
    assert "옛 업로드 3개는 제외" in rep


def test_지평_밖은_빼고_안은_넣는다(uploads):
    _pkg(uploads, "YT-20260501-003", longform_at=_utc_in(24 * 3), shorts_at=_utc_in(24 * 40))
    rep = P.schedule_report(["ko"], days=14)
    assert "롱폼제목" in rep
    assert "숏폼1" not in rep


def test_업로드_안된_것은_일정에_없다(uploads):
    out = uploads / "YT-20260501-004"
    out.mkdir()
    (out / "upload_package.json").write_text(json.dumps(
        {"longform": {"title": "미업로드"}, "shorts": []}), encoding="utf-8")
    assert P.scheduled_items("ko") == []


def test_깨진_패키지는_건너뛴다(uploads):
    out = uploads / "YT-20260501-005"
    out.mkdir()
    (out / "upload_package.json").write_text("{깨짐", encoding="utf-8")
    assert P.scheduled_items("ko") == []   # 예외 없이


def test_채널_정규식으로_가른다(uploads):
    _pkg(uploads, "YT-20260501-006", longform_at=_utc_in(5), shorts_at=_utc_in(6))
    _pkg(uploads, "YT-20260501-007-JA", longform_at=_utc_in(5), shorts_at=_utc_in(6))
    assert all(i.market == "ko" for i in P.scheduled_items("ko"))
    assert {i.video_id for i in P.scheduled_items("ko")} == {"YT-20260501-006"}
    assert {i.video_id for i in P.scheduled_items("ja")} == {"YT-20260501-007-JA"}
