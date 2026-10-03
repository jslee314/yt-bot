"""채널에서 '올라갔지만 공개도 예약도 안 된' 영상을 찾는다.

업로드가 성공하면 파이프라인은 "성공"으로 기록하고 끝난다. 그 뒤 공개 시각을
못 받아 private로 남아도 아무 데도 남지 않는다 — 실제로 숏폼 11개가 5개월간
그렇게 묻혀 있었다. 이 스크립트가 그 구멍을 메운다.

yt-bot의 venv에는 google-api 라이브러리가 없고 YouTube 인증(token.json)은
yt-upload에 있으므로, yt-upload 디렉토리에서 PYTHON_BIN으로 실행하고
yt-upload의 config를 그대로 쓴다.

    cd <yt-upload> && /usr/local/bin/python3 <yt-bot>/tools/stuck_videos.py <yt-upload>

표준출력 마지막 줄에 JSON 배열을 찍는다.
"""

import json
import sys
import warnings

warnings.filterwarnings("ignore")  # google.api_core의 Python 버전 경고 소음 제거

upload_dir = sys.argv[1]
sys.path.insert(0, upload_dir)

import config  # noqa: E402  — yt-upload/config.py (sys.path 삽입 뒤)
from google.auth.transport.requests import Request  # noqa: E402
from google.oauth2.credentials import Credentials  # noqa: E402
from googleapiclient.discovery import build  # noqa: E402


def main() -> int:
    creds = Credentials.from_authorized_user_file(
        str(config.YOUTUBE_TOKEN_FILE), config.YOUTUBE_API_SCOPES
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        config.YOUTUBE_TOKEN_FILE.write_text(creds.to_json())
    yt = build("youtube", "v3", credentials=creds)

    ch = yt.channels().list(part="contentDetails,snippet", mine=True).execute()
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    channel_title = ch["items"][0]["snippet"]["title"]  # 어느 채널 토큰으로 돌았는지 봇이 보여준다

    ids, token = [], None
    while True:
        r = yt.playlistItems().list(
            part="contentDetails", playlistId=uploads, maxResults=50, pageToken=token
        ).execute()
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        token = r.get("nextPageToken")
        if not token:
            break

    stuck = []
    for i in range(0, len(ids), 50):
        r = yt.videos().list(
            part="status,snippet,contentDetails", id=",".join(ids[i : i + 50])
        ).execute()
        for v in r["items"]:
            st = v["status"]
            # public이 아니면서 공개 예약도 없는 것 = 방치
            if st.get("privacyStatus") != "public" and not st.get("publishAt"):
                stuck.append(
                    {
                        "id": v["id"],
                        "title": v["snippet"]["title"],
                        "privacy": st.get("privacyStatus"),
                        "uploaded": v["snippet"]["publishedAt"][:10],
                        "duration": v["contentDetails"].get("duration", ""),
                    }
                )

    stuck.sort(key=lambda x: x["uploaded"])
    print(json.dumps({"total": len(ids), "channel": channel_title, "stuck": stuck}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
