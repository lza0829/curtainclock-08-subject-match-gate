from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.services.ready import adjudicate


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bump(conn: sqlite3.Connection, key: str, delta: int) -> int:
    row = conn.execute("SELECT value FROM watermarks WHERE key=?", (key,)).fetchone()
    cur = int(row["value"]) if row else 0
    nxt = cur + delta
    conn.execute(
        "INSERT INTO watermarks(key, value, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, nxt, _now()),
    )
    return nxt


def _conflict_mode(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT value FROM settings WHERE key='conflict_mode'"
    ).fetchone()
    return row["value"] if row else "reject"


def open_lease(conn: sqlite3.Connection, session_code: str) -> dict:
    # 调用方以 BEGIN IMMEDIATE 持写锁进入。会话状态先读，裁决在锁内做，
    # 保证「检查替身空闲 → 插租约」对并发事务原子可见：
    # 后拿锁的事务必看到前者已提交的占用，杜绝同一替身双占。
    session = conn.execute(
        "SELECT * FROM sessions WHERE code=?", (session_code,)
    ).fetchone()
    if session is None:
        raise ValueError(f"批窗不存在：{session_code}")
    if session["status"] == "live":
        raise ValueError("批窗已在上课，勿重复开窗")
    if session["status"] == "done":
        raise ValueError("批窗已结束")

    # 唯一裁决入口（写锁内重算）：类型门禁 + 替身链 + 算力槽/执行器就绪
    verdict = adjudicate(conn, session)
    if not verdict["ready"]:
        mode = _conflict_mode(conn)
        for reason in verdict["reasons"]:
            kind = "room" if "算力槽" in reason else "teacher"
            resource = (
                session["room_code"]
                if kind == "room"
                else session["teacher_code"]
            )
            # 全链失败/不匹配在此留下门禁痕迹（冲突行 + 冲突水位）
            conn.execute(
                "INSERT INTO conflicts(kind, session_code, resource_code, day, start_min, end_min, reason, created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    kind,
                    session_code,
                    resource,
                    session["day"],
                    session["start_min"],
                    session["end_min"],
                    reason,
                    _now(),
                ),
            )
            _bump(conn, "conflict_count", 1)
        return {
            "ok": False,
            "error": "；".join(verdict["reasons"]),
            "conflict_mode": mode,
        }

    actual_teacher = verdict["actual_teacher"]
    n = conn.execute("SELECT COUNT(*) c FROM leases").fetchone()["c"] + 1
    lease_no = f"L-{session['day'].replace('-', '')}-{n:04d}"
    conn.execute(
        "INSERT INTO leases(lease_no, session_code, room_code, teacher_code, day, "
        "start_min, end_min, status, opened_at, primary_teacher_code, substitute_hit) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            lease_no,
            session_code,
            session["room_code"],
            actual_teacher,
            session["day"],
            session["start_min"],
            session["end_min"],
            "open",
            _now(),
            session["teacher_code"] if verdict["use_substitute"] else None,
            verdict["substitute_hit"],
        ),
    )
    conn.execute(
        "UPDATE sessions SET status='live' WHERE code=?", (session_code,)
    )
    # 水位按实执行器占：占用的就是替身时，也只计实执行器这一份
    open_n = _bump(conn, "open_leases", 1)
    return {
        "ok": True,
        "lease_no": lease_no,
        "session_code": session_code,
        "status": "open",
        "open_leases": open_n,
        "type_mismatch": verdict["type_mismatch"],
        "use_substitute": verdict["use_substitute"],
        "primary_teacher": session["teacher_code"],
        "actual_teacher": actual_teacher,
        "substitute_hit": verdict["substitute_hit"],
    }


def close_lease(conn: sqlite3.Connection, lease_no: str) -> dict:
    lease = conn.execute(
        "SELECT * FROM leases WHERE lease_no=?", (lease_no,)
    ).fetchone()
    if lease is None:
        raise ValueError(f"租约不存在：{lease_no}")
    if lease["status"] != "open":
        raise ValueError("租约不在占用态")
    conn.execute(
        "UPDATE leases SET status='closed', closed_at=? WHERE lease_no=?",
        (_now(), lease_no),
    )
    conn.execute(
        "UPDATE sessions SET status='done' WHERE code=?",
        (lease["session_code"],),
    )
    open_n = _bump(conn, "open_leases", -1)
    return {
        "lease_no": lease_no,
        "status": "closed",
        "open_leases": open_n,
    }
