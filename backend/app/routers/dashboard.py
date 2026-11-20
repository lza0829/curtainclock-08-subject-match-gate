from __future__ import annotations

from fastapi import APIRouter

from app.db import connect

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard():
    conn = connect()
    try:
        day_row = conn.execute(
            "SELECT value FROM settings WHERE key='fixture_day'"
        ).fetchone()
        day = day_row["value"] if day_row else None
        open_leases = conn.execute(
            "SELECT value FROM watermarks WHERE key='open_leases'"
        ).fetchone()
        conflicts = conn.execute(
            "SELECT value FROM watermarks WHERE key='conflict_count'"
        ).fetchone()
        live_n = conn.execute(
            "SELECT COUNT(*) c FROM sessions WHERE status='live'"
        ).fetchone()["c"]
        draft_n = conn.execute(
            "SELECT COUNT(*) c FROM sessions WHERE status='draft'"
        ).fetchone()["c"]
        # 不匹配计数：批窗作业类型与主执行器能力标签不一致即计数（裁决同口径）
        mismatch_n = conn.execute(
            "SELECT COUNT(*) c FROM sessions s "
            "JOIN teachers t ON t.code = s.teacher_code "
            "WHERE t.subject <> s.subject"
        ).fetchone()["c"]
        # 替身计数：租约由替身落库（substitute_hit 非空）即替身租约
        substitute_n = conn.execute(
            "SELECT COUNT(*) c FROM leases WHERE substitute_hit IS NOT NULL"
        ).fetchone()["c"]
        open_substitute_n = conn.execute(
            "SELECT COUNT(*) c FROM leases "
            "WHERE substitute_hit IS NOT NULL AND status='open'"
        ).fetchone()["c"]
        return {
            "fixture_day": day,
            "open_leases": int(open_leases["value"]) if open_leases else 0,
            "conflict_count": int(conflicts["value"]) if conflicts else 0,
            "live_sessions": live_n,
            "draft_sessions": draft_n,
            "mismatch_sessions": mismatch_n,
            "substitute_leases": substitute_n,
            "open_substitute_leases": open_substitute_n,
        }
    finally:
        conn.close()
