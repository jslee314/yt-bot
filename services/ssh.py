"""SSH로 로컬 PC에 접속하여 명령 실행. paramiko 사용."""

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
        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=300)
            out = stdout.read().decode()
            err = stderr.read().decode()
        finally:
            self.client.close()
        return out, err

    def write_file(self, remote_path: str, content: str):
        """원격 파일 쓰기 (selected_text.json 등)"""
        self.connect()
        try:
            sftp = self.client.open_sftp()
            with sftp.open(remote_path, "w") as f:
                f.write(content)
            sftp.close()
        finally:
            self.client.close()

    def read_file(self, remote_path: str) -> str:
        """원격 파일 읽기"""
        self.connect()
        try:
            sftp = self.client.open_sftp()
            with sftp.open(remote_path, "r") as f:
                content = f.read().decode()
            sftp.close()
        finally:
            self.client.close()
        return content

    def download_file(self, remote_path: str, local_path: str):
        """원격 파일 다운로드 (썸네일 이미지 등)"""
        self.connect()
        try:
            sftp = self.client.open_sftp()
            sftp.get(remote_path, local_path)
            sftp.close()
        finally:
            self.client.close()


ssh = SSHClient()
