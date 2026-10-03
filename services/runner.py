"""로컬 명령 실행기 — 봇이 맥에서 직접 돌 때 사용 (SSH 대체).

services/ssh.py(paramiko)와 동일한 인터페이스를 제공하므로 핸들러는 그대로 쓴다.
봇이 파이프라인과 같은 맥에서 돌기 때문에 SSH·DDNS·포트개방이 전부 불필요하다.

긴 작업(파이프라인 완주)은 execute()로 기다리면 텔레그램 콜백이 타임아웃되므로
spawn()으로 백그라운드에 띄우고 로그 파일로 추적한다.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

from config import PATH_PREPEND, SHELL_TIMEOUT

logger = logging.getLogger(__name__)


def _env() -> dict:
    """homebrew 경로를 앞에 붙인 환경 — ffmpeg/ffprobe 탐색 보장."""
    env = os.environ.copy()
    env["PATH"] = f"{PATH_PREPEND}:{env.get('PATH', '')}"
    return env


class LocalRunner:
    """SSHClient와 같은 메서드 시그니처를 갖는 로컬 실행기."""

    def execute(self, command: str, timeout: int | None = None) -> tuple[str, str]:
        """명령을 완료까지 실행하고 (stdout, stderr) 반환."""
        logger.info("exec: %s", command)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout or SHELL_TIMEOUT,
                env=_env(),
            )
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(
                f"명령이 {timeout or SHELL_TIMEOUT}초를 넘겼습니다. "
                "긴 작업은 spawn()을 쓰세요."
            ) from e
        return proc.stdout, proc.stderr

    def spawn(self, command: str, log_path: str | Path) -> int:
        """명령을 백그라운드로 띄우고 PID 반환. 출력은 log_path에 append."""
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("spawn: %s (log=%s)", command, log_path)
        with log_path.open("a") as log:
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=_env(),
                start_new_session=True,  # 봇이 죽어도 작업은 계속
            )
        return proc.pid

    def read_file(self, path: str) -> str:
        return Path(path).expanduser().read_text(encoding="utf-8")

    def write_file(self, path: str, content: str):
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def download_file(self, src: str, dst: str):
        """SSH download_file 대응 — 로컬에서는 단순 복사."""
        dst_p = Path(dst).expanduser()
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(src).expanduser(), dst_p)


runner = LocalRunner()
