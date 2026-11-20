# Curtainclock（幕窗钟）

骨架：**批窗定义 → 算力槽/执行器资源依赖就绪 → 开窗租约占用 → 关窗释放与冲突水位互证**

- 前端：http://127.0.0.1:6100 （React + Vite）
- API：http://127.0.0.1:11100

## 作业类型门禁与替身链（全局唯一裁决）

批窗带作业类型（`sessions.subject`，ETL/BI），执行器挂能力标签（`teachers.subject`）。
全系统只贯彻一种口径——**类型驱动替身链**，就绪判定（`GET /sessions`）与开窗
（`POST /leases/open`）共用 `app/services/ready.py::adjudicate` 同一函数，前端不做独立过滤：

1. **类型匹配**：主执行器能力 = 作业类型 → 走主执行器，检查启用与空闲；
2. **类型不匹配**：主执行器**禁止占用**（ETL 窗不可能落到仅挂 BI 的执行器），
   按 `substitute_chains` 替身优先级表（`position` 从 1 升序）逐个找
   **能力匹配 + 启用 + 时段空闲**者，取最高位命中；
3. **替身命中**：租约落实执行器，并记录 `primary_teacher_code`（主执行器）与
   `substitute_hit`（命中序号）；`open_leases` 水位按实执行器只计一份；
4. **全链失败**：不写租约、批窗不转 live、`open_leases` 不加，冲突行落库留门禁痕迹，
   `conflict_count` +1，接口返回 409；
5. **并发**：开窗在 `BEGIN IMMEDIATE` 写锁事务内重算裁决，替身落库与开窗同事务；
   两路抢同一替身时后拿锁者必看到前者占用，绝不双占。

总览另出两个同源计数：类型不匹配批窗数（session 与主执行器 subject 比对）、
替身租约数（`leases.substitute_hit IS NOT NULL`，含在途数）。
核对脚本：`python -I _check_substitute.py`（独立临时库，覆盖直挂/替身命中/全链失败/并发双占）。

## 本地冒烟（推荐）

```powershell
cd D:\Asolo11\claude-workspace\curtainclock\source
# 本机若无 3.11：py -V:Astral/CPython3.11.15 -m venv .venv
py -V:Astral/CPython3.11.15 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:PYTHONPATH = "$PWD\backend"
Start-Process .\.venv\Scripts\uvicorn.exe -ArgumentList 'app.main:app','--host','127.0.0.1','--port','11100' -WorkingDirectory "$PWD\backend"
cd frontend
# 前端需 Node ≥18；不足时用 docker compose 起 web
npm install
npm run dev
```

浏览器打开 http://127.0.0.1:6100 ：开一节课 → 同算力槽冲突 → 关窗释放。

## Docker

```powershell
docker compose up -d --build
```
