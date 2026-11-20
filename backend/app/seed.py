from __future__ import annotations

from datetime import datetime, timezone

from app.db import connect, init_db


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_if_empty() -> None:
    init_db()
    conn = connect()
    try:
        n = conn.execute("SELECT COUNT(*) c FROM rooms").fetchone()["c"]
        if n > 0:
            return
        # rooms 表 = 算力槽；teachers 表 = 执行器（库表名兼容底座，界面/题面用语为数仓皮）
        rooms = [
            ("S-ETL-01", "ETL 主槽 A", 80),
            ("S-ETL-02", "ETL 主槽 B", 30),
            ("S-BI-01", "报表槽甲", 40),
            ("S-BI-02", "报表槽乙", 40),
        ]
        for code, name, cap in rooms:
            conn.execute(
                "INSERT INTO rooms(code, name, capacity, active) VALUES(?,?,?,1)",
                (code, name, cap),
            )
        teachers = [
            ("E-PIPE-01", "管道执行器甲", "ETL"),
            ("E-PIPE-02", "管道执行器乙", "ETL"),
            ("E-BI-01", "报表执行器甲", "BI"),
            ("E-BI-02", "报表执行器乙", "BI"),
        ]
        for code, name, subject in teachers:
            conn.execute(
                "INSERT INTO teachers(code, name, subject, active) VALUES(?,?,?,1)",
                (code, name, subject),
            )
        day = "2026-11-20"
        sessions = [
            ("W-DIM-01", "维表刷新窗", "ETL", "S-ETL-01", "E-PIPE-01", day, 9 * 60, 10 * 60 + 30),
            ("W-FACT-01", "事实入湖窗", "ETL", "S-ETL-02", "E-PIPE-02", day, 9 * 60, 10 * 60 + 30),
            ("W-RPT-01", "日报物化窗", "BI", "S-BI-01", "E-BI-01", day, 13 * 60, 14 * 60 + 30),
            ("W-RPT-02", "看板刷新窗", "BI", "S-BI-02", "E-BI-02", day, 13 * 60, 14 * 60 + 30),
            # 主执行器仅挂 BI 能力，作业却是 ETL：类型不匹配，须走替身链
            ("W-SUB-01", "跨槽补数窗（替身命中）", "ETL", "S-ETL-01", "E-BI-01", day, 15 * 60, 16 * 60),
            # 主执行器 BI，替身链上没有任何 ETL 能力者：全链失败进冲突
            ("W-SUB-02", "夜间重算窗（全链失败）", "ETL", "S-ETL-02", "E-BI-02", day, 16 * 60 + 30, 17 * 60 + 30),
        ]
        for row in sessions:
            conn.execute(
                "INSERT INTO sessions(code, title, subject, room_code, teacher_code, day, start_min, end_min, status) "
                "VALUES(?,?,?,?,?,?,?,?, 'draft')",
                row,
            )
        # 替身优先级表：(主执行器, 优先级序号, 替身执行器)，序号从 1 开始
        chains = [
            # E-BI-01 的链：首位是同型 BI（对 ETL 作业不匹配，须跳过），
            # 第二位才是 ETL 能力的 E-PIPE-01——验证按类型过滤而非只取首位
            ("E-BI-01", 1, "E-BI-02"),
            ("E-BI-01", 2, "E-PIPE-01"),
            # E-BI-02 的链全是 BI 能力：ETL 作业全链失败
            ("E-BI-02", 1, "E-BI-01"),
            # ETL 执行器也配链，覆盖主执行器为 ETL 的不匹配场景
            ("E-PIPE-01", 1, "E-PIPE-02"),
            ("E-PIPE-02", 1, "E-PIPE-01"),
        ]
        for primary, position, substitute in chains:
            conn.execute(
                "INSERT INTO substitute_chains(primary_code, position, substitute_code) "
                "VALUES(?,?,?)",
                (primary, position, substitute),
            )
        conn.execute(
            "INSERT INTO watermarks(key, value, updated_at) VALUES('open_leases', 0, ?)",
            (_now(),),
        )
        conn.execute(
            "INSERT INTO watermarks(key, value, updated_at) VALUES('conflict_count', 0, ?)",
            (_now(),),
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('conflict_mode', 'reject')",
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('fixture_day', ?)",
            (day,),
        )
        conn.commit()
    finally:
        conn.close()
