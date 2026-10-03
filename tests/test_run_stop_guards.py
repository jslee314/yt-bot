"""/run force 지출 상한 · /stop 프로세스 그룹 종료.

배경:
  - force 는 1회에 TTS 약 6,242자 + 채널 일일 쿼터 전부(약 6,300원)를 쓰는데
    동시 실행만 막혀 있어 연속 호출이 무제한이었다.
  - /stop 은 `pkill -f auto_pipeline.sh` 로 오케스트레이터만 죽였다. 자식은
    start_new_session=True 로 떨어져 나와 살아남아, "중단했다"고 답하면서
    TTS·이미지 비용이 계속 나갔다.
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import services.pipeline as P  # noqa: E402


# ── 분류기: 실행 중인 것만 고르고 뷰어는 놓아둔다 ──────────────
@pytest.mark.parametrize("cmd", [
    "bash mirror_build.sh YT-20260425-003-JA",
    "caffeinate -i env MARKET=ja bash mirror_build.sh YT-x",
    "/usr/bin/python3 make_all.py --script a.txt",
    "/bin/bash /Users/x/yt-pipeline/auto_pipeline.sh",
])
def test_실행중인_것은_잡는다(cmd):
    assert P._is_pipeline_cmd(cmd)


@pytest.mark.parametrize("cmd", [
    "tail -f /Users/x/yt-pipeline/auto_pipeline.sh",   # 로그 뷰어
    "grep -n auto_pipeline.sh README.md",
    "vim auto_pipeline.sh",
    "less make_all.py",
    "/bin/zsh -c 'pgrep -f auto_pipeline.sh'",          # 셸 래퍼 본문
    "",
])
def test_뷰어와_래퍼는_놓아둔다(cmd):
    assert not P._is_pipeline_cmd(cmd)


# ── 종료: 자식까지 같이 죽는가 ───────────────────────────────
@pytest.fixture
def fake_pipeline(tmp_path):
    """세션 리더 + 자식 — 실제 파이프라인과 같은 모양(start_new_session)."""
    script = tmp_path / "make_all.py"
    script.write_text("import time\nwhile True: time.sleep(0.2)\n", encoding="utf-8")
    parent = tmp_path / "auto_pipeline.sh"
    parent.write_text(
        f'#!/bin/bash\n"{sys.executable}" "{script}" &\nwait\n', encoding="utf-8")
    parent.chmod(0o755)
    proc = subprocess.Popen(["/bin/bash", str(parent)], start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.2)
    yield proc
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


def _alive(pid: int) -> bool:
    """좀비는 죽은 것으로 센다.

    os.kill(pid, 0) 은 좀비에도 성공한다 — 부모(pytest)가 아직 거두지 않은
    프로세스가 '살아있음'으로 잡혀 테스트가 거짓 실패한다. ps 의 상태 문자가
    Z 면 이미 끝난 것이다.
    """
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                         capture_output=True, text=True).stdout.strip()
    return bool(out) and not out.startswith("Z")


def test_stop_all_이_자식까지_멈춘다(fake_pipeline, monkeypatch):
    pgid = os.getpgid(fake_pipeline.pid)
    children = subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True, text=True).stdout.split()
    assert len(children) >= 2, "부모+자식이 떠 있어야 하는 테스트"

    # 이 테스트가 만든 그룹만 보도록 좁힌다
    real = P.running_procs
    monkeypatch.setattr(P, "running_procs",
                        lambda: [t for t in real() if t[1] == pgid])

    r = P.stop_all(grace=1.5)
    assert pgid in r["pgids"]
    assert not r["survived"], f"살아남음: {r['survived']}"
    fake_pipeline.wait(timeout=5)          # 부모를 거둬 좀비를 없앤다
    time.sleep(0.3)
    still = [c for c in children if _alive(int(c))]
    assert not still, f"자식이 살아남았다 — 비용이 계속 나간다: {still}"


def test_stop_all_은_봇_자신의_그룹을_건드리지_않는다():
    """running_procs 는 자기 프로세스 그룹을 절대 반환하지 않는다."""
    my_pgid = os.getpgid(os.getpid())
    assert all(pgid != my_pgid for _, pgid, _ in P.running_procs())


# ── force 상한 ──────────────────────────────────────────────
def test_force_상한_집계(tmp_path, monkeypatch):
    import importlib
    db = tmp_path / "state.db"
    monkeypatch.setenv("DB_PATH", str(db))
    import config, services.state as S
    importlib.reload(config); importlib.reload(S)
    S.init_db()
    assert S.count_forced_runs() == 0
    S.record_forced_run("ko", "YT-20260425-005")
    S.record_forced_run("ko", "YT-20260425-006")
    assert S.count_forced_runs() == 2
    assert S.count_forced_runs("1999-01") == 0   # 다른 달은 섞이지 않는다
