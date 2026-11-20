# -*- coding: utf-8 -*-
"""0-1 API smoke against running server on 11100.

覆盖：直挂开窗 → 替身命中（主不匹配、链上有匹配者，租约实执行器非主）
→ 全链失败进冲突（不落租约、水位不加）→ 关窗释放 → 水位互证。
前置：服务以种子库启动（W-SUB-01/W-SUB-02 为类型不匹配批窗）。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:11100/api"


def call(method: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"detail": raw}
        return e.code, payload


def main() -> None:
    st, dash = call("GET", "/dashboard")
    assert st == 200, dash
    print("dashboard", dash)
    assert dash["mismatch_sessions"] >= 2, dash

    # 类型匹配 → 主执行器直挂
    st, direct = call("POST", "/leases/open", {"session_code": "W-DIM-01"})
    assert st == 200 and direct["use_substitute"] is False, direct
    print("direct", direct)

    # 主不匹配、链上有匹配者 → 成功且租约实执行器非主，带替身序号
    st, sub = call("POST", "/leases/open", {"session_code": "W-SUB-01"})
    assert st == 200, sub
    assert sub["use_substitute"] is True and sub["actual_teacher"] != sub["primary_teacher"], sub
    assert sub["substitute_hit"] == 2 and sub["actual_teacher"] == "E-PIPE-01", sub
    print("substitute", sub)

    # 全链失败 → 409 冲突，不落租约
    st, before_leases = call("GET", "/leases")
    st, conflict = call("POST", "/leases/open", {"session_code": "W-SUB-02"})
    assert st == 409 and "全链失败" in conflict["detail"], conflict
    print("conflict", conflict)
    st, after_leases = call("GET", "/leases")
    assert len(after_leases) == len(before_leases), "全链失败不得落租约"

    # 租约快照留替身痕迹，且不匹配主执行器零占用
    assert any(
        L["session_code"] == "W-SUB-01"
        and L["teacher_code"] == "E-PIPE-01"
        and L["primary_teacher_code"] == "E-BI-01"
        and L["substitute_hit"] == 2
        for L in after_leases
    ), after_leases
    assert all(L["teacher_code"] != "E-BI-02" for L in after_leases), "不匹配主执行器被占用"

    st, closed = call("POST", "/leases/close", {"lease_no": direct["lease_no"]})
    assert st == 200, closed
    print("close", closed)

    st, dash2 = call("GET", "/dashboard")
    assert st == 200, dash2
    assert dash2["conflict_count"] >= 1, dash2
    assert dash2["substitute_leases"] >= 1 and dash2["open_substitute_leases"] >= 1, dash2
    print("dashboard_after", dash2)
    print("SMOKE_OK")


if __name__ == "__main__":
    main()
