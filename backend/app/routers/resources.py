from __future__ import annotations

from fastapi import APIRouter

from app.db import connect

router = APIRouter(tags=["resources"])


@router.get("/rooms")
def list_rooms():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT code, name, capacity, active FROM rooms ORDER BY code"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/teachers")
def list_teachers():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT code, name, subject, active FROM teachers ORDER BY code"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/substitute-chains")
def substitute_chains():
    """替身优先级表：与开窗裁决读取同一张表、同一顺序。"""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT sc.primary_code, sc.position, sc.substitute_code, "
            "t.subject AS substitute_subject, t.active AS substitute_active "
            "FROM substitute_chains sc "
            "JOIN teachers t ON t.code = sc.substitute_code "
            "ORDER BY sc.primary_code, sc.position"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
