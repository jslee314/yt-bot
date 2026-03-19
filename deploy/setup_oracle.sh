#!/bin/bash
set -e

# 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# Python 3.11+
sudo apt install -y python3.11 python3.11-venv python3-pip

# 프로젝트 클론
cd ~
git clone https://github.com/jslee314/yt-bot.git
cd yt-bot

# 가상환경
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# .env 설정
cp .env.example .env
echo ">>> .env 파일을 편집하세요: nano .env"

# SSH 키 디렉토리
mkdir -p deploy/ssh_keys
echo ">>> 로컬 PC 접속용 SSH 비밀키를 deploy/ssh_keys/에 복사하세요."

# systemd 서비스 등록
sudo cp deploy/systemd/yt-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable yt-bot

echo ">>> 설정 완료 후 실행: sudo systemctl start yt-bot"
