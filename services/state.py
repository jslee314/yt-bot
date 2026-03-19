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
