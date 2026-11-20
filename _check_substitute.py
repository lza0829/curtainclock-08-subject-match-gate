# -*- coding: utf-8 -*-
"""替身链裁决的端到端核对（不依赖运行中的服务，直接打服务层 + 临时库）。

覆盖题面核对点（全局口径 = 类型驱动替身链）：
1. 类型匹配 → 主执行器直挂；
2. 主不匹配、链上有匹配且空闲者 → 成功，租约实执行器非主、带替身序号；
   链首同型不匹配须被跳过（按类型过滤而非取首位）；
3. 全链失败 → 进冲突、不落租约、open_leases 水位不加；
4. 不匹配时主执行器绝不出现于租约；
5. 并发两路抢同一替身 → 仅一路成功，无双占；
6. 总览不匹配/替身计数与裁决同源。
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time

_tmp = tempfile.mkdtemp(prefix="curtainclock_test_")
os.environ["CURTAINCLOCK_DB"] = os.path.join(_tmp, "test.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from app import config  # noqa: E402
from pathlib import Path  # noqa: E402

config.DB_PATH = Path(os.environ["CURTAINCLOCK_DB"])
import app.db as db_mod  # noqa: E402

db_mod.DB_PATH = config.DB_PATH
from app.db import connect, init_db, transaction  # noqa: E402
from app.services import lease as lease_svc  # noqa: E402
from app.services.ready import adjudicate  # noqa: E402

DAY = "2026-11-20"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        failures.append(name)


def setup() -> None:
    init_db()
    with transaction() as c:
        for code, name, cap in [
            ("S-ETL-01", "ETL槽A", 80),
            ("S-BI-01", "BI槽甲", 40),
        ]:
            c.execute("INSERT INTO rooms(code,name,capacity,active) VALUES(?,?,?,1)", (code, name, cap))
        for code, name, subject in [
            ("E-PIPE-01", "管道甲", "ETL"),
            ("E-PIPE-02", "管道乙", "ETL"),
            ("E-BI-01", "报表甲", "BI"),
            ("E-BI-02", "报表乙", "BI"),
        ]:
            c.execute("INSERT INTO teachers(code,name,subject,active) VALUES(?,?,?,1)", (code, name, subject))
        c.execute("INSERT INTO watermarks(key,value,updated_at) VALUES('open_leases',0,'t')")
        c.execute("INSERT INTO watermarks(key,value,updated_at) VALUES('conflict_count',0,'t')")
        c.execute("INSERT INTO settings(key,value) VALUES('conflict_mode','reject')")
        # E-BI-01 链：首号同型 BI（须跳过），二号 ETL 匹配
        c.execute("INSERT INTO substitute_chains(primary_code,position,substitute_code) VALUES('E-BI-01',1,'E-BI-02')")
        c.execute("INSERT INTO substitute_chains(primary_code,position,substitute_code) VALUES('E-BI-01',2,'E-PIPE-01')")
        # E-BI-02 链：全 BI，ETL 作业必全链失败
        c.execute("INSERT INTO substitute_chains(primary_code,position,substitute_code) VALUES('E-BI-02',1,'E-BI-01')")
        # E-PIPE-01 链
        c.execute("INSERT INTO substitute_chains(primary_code,position,substitute_code) VALUES('E-PIPE-01',1,'E-PIPE-02')")


def add_session(c, code, subject, room, teacher, s=900, e=960) -> None:
    c.execute(
        "INSERT INTO sessions(code,title,subject,room_code,teacher_code,day,start_min,end_min,status)"
        " VALUES(?,?,?,?,?,?,?,?,'draft')",
        (code, code, subject, room, teacher, DAY, s, e),
    )


def wm(key: str) -> int:
    with connect() as c:
        row = c.execute("SELECT value FROM watermarks WHERE key=?", (key,)).fetchone()
        return int(row["value"])


def test_match_direct() -> None:
    with transaction() as c:
        add_session(c, "W-OK", "ETL", "S-ETL-01", "E-PIPE-01")
    with transaction() as c:
        s = c.execute("SELECT * FROM sessions WHERE code='W-OK'").fetchone()
        v = adjudicate(c, s)
        check("类型匹配-裁决就绪", v["ready"] and not v["type_mismatch"] and not v["use_substitute"])
        r = lease_svc.open_lease(c, "W-OK")
        check("类型匹配-开窗成功", r["ok"] and r["actual_teacher"] == "E-PIPE-01")
    with connect() as c:
        lease = c.execute("SELECT * FROM leases WHERE session_code='W-OK'").fetchone()
        check("类型匹配-租约落主执行器", lease["teacher_code"] == "E-PIPE-01" and lease["substitute_hit"] is None)


def test_substitute_hit() -> None:
    with transaction() as c:
        add_session(c, "W-SUB", "ETL", "S-ETL-01", "E-BI-01", s=1000, e=1060)
    with transaction() as c:
        s = c.execute("SELECT * FROM sessions WHERE code='W-SUB'").fetchone()
        v = adjudicate(c, s)
        check(
            "替身命中-跳过链首同型、取二号匹配",
            v["ready"] and v["type_mismatch"] and v["use_substitute"]
            and v["actual_teacher"] == "E-PIPE-01" and v["substitute_hit"] == 2,
            str({k: v[k] for k in ("type_mismatch", "actual_teacher", "substitute_hit")}),
        )
        r = lease_svc.open_lease(c, "W-SUB")
        check("替身命中-开窗返回替身", r["ok"] and r["use_substitute"] and r["actual_teacher"] == "E-PIPE-01")
    with connect() as c:
        lease = c.execute("SELECT * FROM leases WHERE session_code='W-SUB'").fetchone()
        check(
            "替身命中-租约实执行器非主且留痕",
            lease["teacher_code"] == "E-PIPE-01"
            and lease["primary_teacher_code"] == "E-BI-01"
            and lease["substitute_hit"] == 2,
        )
        bad = c.execute(
            "SELECT COUNT(*) c FROM leases WHERE session_code='W-SUB' AND teacher_code='E-BI-01'"
        ).fetchone()["c"]
        check("替身命中-不匹配主执行器零占用", bad == 0)


def test_chain_all_fail() -> None:
    before_open = wm("open_leases")
    before_conf = wm("conflict_count")
    with transaction() as c:
        add_session(c, "W-FAIL", "ETL", "S-ETL-01", "E-BI-02", s=1100, e=1160)
    with transaction() as c:
        s = c.execute("SELECT * FROM sessions WHERE code='W-FAIL'").fetchone()
        v = adjudicate(c, s)
        check("全链失败-裁决不就绪且有门禁原因", not v["ready"] and v["type_mismatch"] and len(v["reasons"]) == 1)
        r = lease_svc.open_lease(c, "W-FAIL")
        check("全链失败-open_lease 返回冲突", r["ok"] is False)
    with connect() as c:
        lease_n = c.execute("SELECT COUNT(*) c FROM leases WHERE session_code='W-FAIL'").fetchone()["c"]
        conf_n = c.execute("SELECT COUNT(*) c FROM conflicts WHERE session_code='W-FAIL'").fetchone()["c"]
        live = c.execute("SELECT status FROM sessions WHERE code='W-FAIL'").fetchone()["status"]
        check("全链失败-不落租约", lease_n == 0)
        check("全链失败-冲突落库留痕", conf_n == 1)
        check("全链失败-批窗未转 live", live == "draft")
    check("全链失败-open_leases 水位不加", wm("open_leases") == before_open)
    check("全链失败-conflict_count 水位 +1", wm("conflict_count") == before_conf + 1)


def test_busy_substitute_skips() -> None:
    # E-PIPE-01 已被 W-SUB 占用（1000-1060）；同学段新窗主挂 E-BI-01，
    # 链首 BI 不匹配、二号 E-PIPE-01 忙 → 全链失败
    with transaction() as c:
        add_session(c, "W-BUSY", "ETL", "S-ETL-01", "E-BI-01", s=1020, e=1080)
    with transaction() as c:
        r = lease_svc.open_lease(c, "W-BUSY")
        check("替身忙-跳过且全链失败进冲突", r["ok"] is False and "全链失败" in r["error"])
    with connect() as c:
        conf = c.execute("SELECT reason FROM conflicts WHERE session_code='W-BUSY'").fetchone()
        check("替身忙-原因含占用租约号", conf is not None and "占用" in conf["reason"])


def test_concurrent_no_double_occupy() -> None:
    # 两个不同批窗同学段、不同算力槽（绕开槽维度），主执行器都不匹配；
    # 在「第三个不相关槽」预置一条占用 E-PIPE-01 的租约（不碰两窗的槽），
    # 使两条链的唯一 ETL 可用替身都收敛到 E-PIPE-02 —— 专打同一替身双占
    with transaction() as c:
        c.execute("INSERT INTO rooms(code,name,capacity,active) VALUES('S-BLK','阻塞槽',1,1)")
        c.execute(
            "INSERT INTO leases(lease_no,session_code,room_code,teacher_code,day,"
            "start_min,end_min,status,opened_at) VALUES('L-BLOCK-1','W-BLOCK','S-BLK',"
            "'E-PIPE-01',?,1180,1280,'open','t')",
            (DAY,),
        )
        add_session(c, "W-C1", "ETL", "S-ETL-01", "E-BI-01", s=1200, e=1260)
        add_session(c, "W-C2", "ETL", "S-BI-01", "E-BI-02", s=1200, e=1260)
        # E-BI-01 链：pos1 BI 跳过、pos2 E-PIPE-01 忙跳过、pos3 E-PIPE-02
        c.execute("INSERT INTO substitute_chains(primary_code,position,substitute_code) VALUES('E-BI-01',3,'E-PIPE-02')")
        # E-BI-02 链：pos1 BI 跳过、pos2 E-PIPE-02
        c.execute("INSERT INTO substitute_chains(primary_code,position,substitute_code) VALUES('E-BI-02',2,'E-PIPE-02')")

    results: list[dict] = []
    errors: list[Exception] = []
    # 强制两路同时抢写锁：barrier 同步后各自进入 BEGIN IMMEDIATE，
    # 必然一路持锁、另一路在 busy_timeout 内排队，拿锁后重算裁决
    barrier = threading.Barrier(2)
    start = threading.Event()

    def worker(code: str) -> None:
        try:
            barrier.wait()
            start.wait()
            with transaction() as conn:
                results.append(lease_svc.open_lease(conn, code))
        except Exception as exc:  # 序列化失败者应走异常或冲突返回，绝不静默双占
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=("W-C1",))
    t2 = threading.Thread(target=worker, args=("W-C2",))
    t1.start(); t2.start()
    # 两路已在 barrier 处汇合，放行后同时抢写锁
    time.sleep(0.2)
    start.set()
    t1.join(); t2.join()

    oks = [r for r in results if r.get("ok")]
    fails = [r for r in results if r.get("ok") is False]
    with connect() as c:
        double = c.execute(
            "SELECT COUNT(*) c FROM leases WHERE teacher_code='E-PIPE-02' AND day=? AND status='open' "
            "AND start_min < 1260 AND end_min > 1200",
            (DAY,),
        ).fetchone()["c"]
        check(
            "并发-同替身仅一路成功（无双占）",
            len(oks) == 1 and len(fails) == 1 and double == 1 and not errors,
            f"oks={len(oks)} fails={len(fails)} rows={double} errors={[str(e) for e in errors]}",
        )
    # 败者无论是卡在算力槽还是替身链，都必须留下冲突行且不得落租约
    with connect() as c:
        loser = "W-C2" if oks and oks[0]["session_code"] == "W-C1" else "W-C1"
        loser_lease = c.execute(
            "SELECT COUNT(*) c FROM leases WHERE session_code=?", (loser,)
        ).fetchone()["c"]
        loser_conf = c.execute(
            "SELECT COUNT(*) c FROM conflicts WHERE session_code=?", (loser,)
        ).fetchone()["c"]
    check("并发-败者留冲突痕迹且不落租约", loser_lease == 0 and loser_conf == 1)


def test_dashboard_counts() -> None:
    with connect() as c:
        mismatch_n = c.execute(
            "SELECT COUNT(*) c FROM sessions s JOIN teachers t ON t.code=s.teacher_code "
            "WHERE t.subject <> s.subject"
        ).fetchone()["c"]
        sub_n = c.execute("SELECT COUNT(*) c FROM leases WHERE substitute_hit IS NOT NULL").fetchone()["c"]
    check("总览-不匹配计数 > 0", mismatch_n >= 3, f"mismatch={mismatch_n}")
    check("总览-替身计数与替身租约一致", sub_n == 2, f"substitute={sub_n}")


if __name__ == "__main__":
    setup()
    test_match_direct()
    test_substitute_hit()
    test_chain_all_fail()
    test_busy_substitute_skips()
    test_concurrent_no_double_occupy()
    test_dashboard_counts()
    if failures:
        print(f"\n{len(failures)} 项失败：{failures}")
        sys.exit(1)
    print("\nALL_CHECKS_PASS")
