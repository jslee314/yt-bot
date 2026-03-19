import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))

# SSH (로컬 PC 접속)
SSH_HOST = os.getenv("SSH_HOST")
SSH_PORT = int(os.getenv("SSH_PORT", "22"))
SSH_USER = os.getenv("SSH_USER")
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH", "deploy/ssh_keys/id_ed25519")

# 로컬 PC 프로젝트 경로
LOCAL_YT_SCRIPT_DIR = os.getenv("LOCAL_YT_SCRIPT_DIR", "~/yt-script")
LOCAL_YT_PRODUCTION_DIR = os.getenv("LOCAL_YT_PRODUCTION_DIR", "~/yt-production")
LOCAL_YT_UPLOAD_DIR = os.getenv("LOCAL_YT_UPLOAD_DIR", "~/yt-upload")

# 상태 DB
DB_PATH = os.getenv("DB_PATH", "state.db")
