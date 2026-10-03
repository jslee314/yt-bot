"""영상별 상태 관리 (SQLite). 봇이 어떤 영상의 어떤 결정이 수정되었는지 추적."""

import sqlite3
from datetime import datetime
from config import DB_PATH


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            video_id TEXT,
            decision_type TEXT,
            original_value TEXT,
            modified_value TEXT,
            modified_at TEXT,
            PRIMARY KEY (video_id, decision_type)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forced_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL,
            video_id TEXT,
            ran_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


# ── /run force 지출 상한 ─────────────────────────────────────
# force 1회 = TTS 약 6,242자 + 이미지 + 채널 일일 쿼터 전부 ≈ 6,300원.
# ElevenLabs Starter 는 월 40,000자이고 정규 운영이 월 3편(18,726자)을 쓰므로,
# force 를 월 3회까지 허용하면 약 37,500자로 한도 직전에서 멈춘다.
# 동시 실행만 막혀 있던 때는 연속 force 가 무제한이었다.
def _month_key(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m")


def count_forced_runs(month: str | None = None) -> int:
    month = month or _month_key()
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM forced_runs WHERE substr(ran_at, 1, 7) = ?", (month,)
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else 0


def record_forced_run(market: str, video_id: str = "") -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO forced_runs (market, video_id, ran_at) VALUES (?, ?, ?)",
        (market, video_id, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def save_decision(video_id: str, decision_type: str, value: str):
    """결정 저장 (hook, thumbnail_text, title, publish_at)"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT OR REPLACE INTO decisions
        (video_id, decision_type, modified_value, modified_at)
        VALUES (?, ?, ?, ?)
        """,
        (video_id, decision_type, value, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_decision(video_id: str, decision_type: str) -> str | None:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT modified_value FROM decisions WHERE video_id=? AND decision_type=?",
        (video_id, decision_type),
    ).fetchone()
    conn.close()
    return row[0] if row else None
