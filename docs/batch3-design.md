# 批次 3 设计文档：后端性能优化（N+1 序列化 + 列表分页 + 子进程并行 + IO 节流）

> 对应 `docs/optimization-plan.md` 批次 3，覆盖问题 #5 / #6 / #7 / #8 / #9 / #25。
> 本文档仅做设计，不包含实现。

---

## 一、解决什么问题

批次 3 聚焦"把同步、串行、懒加载的查询与外部操作改为批量、并行、节流"。当前后端存在 6 类性能瓶颈，在数据量增长时会显著拖慢列表接口与轮询接口：

| # | 问题 | 现状 | 影响 |
|---|---|---|---|
| 5 | `list_jobs` 为每个 job 重算均值 | `api/benchmarks.py` `_serialize` 对每个 job 遍历 `job.attempts` 重算 `average`，而 `summary_json` 已存有结果 | 列表 200 个 job 触发 200 次懒加载 + 重算 |
| 6 | `serialize_queue` 的 N+1 | `task_queue.py` 每个队列项 `db.get(BenchmarkTask)` + 可选 `db.get(BenchmarkJob)`，`session_stats` 还全表扫 `BenchmarkJob` | 该接口被 TasksPage **每 1 秒轮询**，N 个队列项 = 每秒 ~2N 次查询 |
| 7 | `list_profiles` 每个 profile 两次全表扫描 | 每个 profile 调 `known_flags(db)` + `canonical_flags(db)`，全表扫 `ArgumentCatalog` | N 个 profile = 2N 次扫描同样数据 |
| 8 | `list_services?with_status=true` 串行 systemctl | 每个服务串行调一次 `systemctl status` 子进程 | N 个服务串行 N 次子进程，列表响应慢 |
| 9 | 下载进度逐 chunk commit | `models_service._run_download` 每 1MB chunk 都 `db.commit()` | 大文件产生数千次磁盘写，影响并发 |
| 25 | 列表接口无分页 | `list_jobs`(limit 200) / `list_profiles` / `list_models` / `list_tasks` / `list_downloads`(limit 100) 均无分页 | 数据量大时单次返回过多，前端无分页 UI |

**核心收益：** 列表与轮询接口从 O(N) 查询降为 O(1) 批量；子进程从 N 次降为 1 次；下载磁盘写从数千次降为数十次；列表支持分页避免一次性返回海量数据。

---

## 二、目标与非目标

### 目标
- #5：列表接口直接用 `summary_json` 中已有 metrics，不再遍历 `job.attempts`；详情接口仍重算（含实时 attempts）。
- #6：`serialize_queue` 一次性批量加载 task / job，`session_stats` 改 `GROUP BY` 聚合查询。
- #7：`list_profiles` 入口一次性加载 flags，传入各 profile 复用（2N → 1）。
- #8：`list_services?with_status=true` 用 `systemctl list-units 'llamalens-*' --output=json` 一次拿全部状态后 join（N → 1）。
- #9：下载进度按"时间 + 字节"双维度节流 commit（默认 2 秒或 16MB 一次），结束再 commit 终态。
- #25：统一 `?offset&limit` 分页 + `{items, total, offset, limit}` 返回结构，前端同步改 5 个列表页为分页 / 无限滚动。

### 非目标（留给后续批次）
- 前端 SSE 推送替代轮询（#10，批次 4）
- 前端 API 抽象层（#17，批次 4）——本批次前端只改分页，不重构 API 层
- Alembic 迁移（#11，批次 5）
- 拆分大文件（#12，批次 5）

---

## 三、关键设计决策（已与用户确认）

| 维度 | 决策 | 说明 |
|---|---|---|
| #25 分页返回结构 | `{items, total, offset, limit}` 包裹对象 | 破坏性变更，本批次同步改前端 5 个列表页 |
| #25 前端边界 | 本批次改前端 | 分页 UI 随后端一起落地，不留半成品 |
| #8 systemctl 方案 | 批量 `list-units` 一次拿全 | 1 次子进程，按 unit_name join |
| #7 flags 策略 | 每请求查一次复用 | list 入口预加载，传入各 profile；无进程内缓存 |

---

## 四、模块 A：list_jobs 轻量化（#5）

### 现状
`api/benchmarks.py` `_serialize(job, include_attempts=False)`：
```python
successful_attempts = [a for a in job.attempts if not a.warmup and a.status == "succeeded"]
for key, values in {"ttft_ms": [...], ...}.items():
    metric = metrics.setdefault(key, {})
    if "average" not in metric:
        metric["average"] = statistics.fmean(values) if values else None
```
即使 `include_attempts=False`（列表场景），仍触发 `job.attempts` 懒加载 + 重算。

### 前提验证
`benchmark.py` 在 job 完成时已把 `metrics[key].average` 写入 `summary_json`（L563-572，L671 commit）。列表场景可直接用。

### 设计
1. `_serialize` 增加参数 `lightweight: bool = False`：
   - `lightweight=True`（列表）：**不访问 `job.attempts`**，直接用 `summary_json` 里的 `metrics`，按需补 `has_unit_snapshot`。`average` 已在 summary 中，无需重算。
   - `lightweight=False`（详情，`include_attempts=True`）：保持现有逻辑（重算 average 作为 attempts 级校验 + 返回 attempts 明细）。
2. `list_jobs` 改为 `_serialize(job, lightweight=True)`。
3. `get_job` 保持 `_serialize(job, include_attempts=True)`（详情仍重算，因 attempts 可能被实时修改）。
4. `create` / `rename` 返回单 job，用 `lightweight=False`（数据量小，且需保证一致）。

### 边界
- `running`/`queued` job 的 `summary_json` 为 `"{}"`，`metrics` 为空，`average` 不存在——列表展示时前端按 `None` 处理（与当前重算结果一致，因 running job 的 attempts 不含 succeeded 项）。
- `failed`/`cancelled` job 同理，summary 可能为空或部分，`average` 为 None，符合预期。

---

## 五、模块 B：serialize_queue 批量化（#6）

### 现状
`task_queue.py` `serialize_queue`：
- 每个队列项 `_serialize_item` → `db.get(BenchmarkTask)` + 可选 `db.get(BenchmarkJob)`
- `session_stats` 全表扫 `BenchmarkJob where queue_session_id == q.session_id`，Python 端循环计数

该接口被 TasksPage 每 1 秒轮询。

### 设计
1. **批量加载 tasks**：一次性 `select(BenchmarkTask).where(BenchmarkTask.id.in_(item_task_ids))`，建 `dict[str, BenchmarkTask]`。
2. **批量加载 jobs**：收集所有 `item.last_run_id`，一次性 `select(BenchmarkJob).where(BenchmarkJob.id.in_(run_ids))`，建 `dict[str, BenchmarkJob]`。
3. **`_serialize_item` 改签名**：接受预加载的 `task` 和 `job` 对象（而非内部 `db.get`），仅做字段拼装。
4. **`session_stats` 改聚合查询**：
   ```sql
   SELECT status, COUNT(*) FROM benchmark_jobs
   WHERE queue_session_id = :session_id GROUP BY status
   ```
   Python 端按 `succeeded/failed/cancelled` 汇总，避免全表扫 + 循环。
5. **空集合守卫**：队列项为空时跳过批量查询，直接返回空 items。

### 性能预估
- N 个队列项：从 ~2N+1 次查询降为 3 次（items + tasks + jobs）+ 1 次聚合 = 4 次。
- 每秒轮询场景下，查询量与队列长度解耦。

---

## 六、模块 C：list_profiles flags 复用（#7）

### 现状
`profiles_service.serialize_profile` → `build_launch_argv` → `known_flags(db)` + `canonical_flags(db)`，每次全表扫 `ArgumentCatalog`。

### 设计
1. **新增内部函数** `_build_argv_with_flags(settings, config, known: set[str], canonical: dict[str, str])`：把 `build_launch_argv` 的核心逻辑拆出，接受预加载的 flags，不再自己查 DB。
2. **`build_launch_argv(db, settings, config)` 保持原签名**（向后兼容，单 profile 场景如 create/update/preview/service 部署仍用），内部调 `_build_argv_with_flags` 并自行加载 flags。
3. **`serialize_profile` 增加可选参数** `flags: tuple[set[str], dict[str, str]] | None = None`：
   - 传入时用传入的 flags（列表场景）
   - 不传入时自行调 `known_flags`/`canonical_flags`（单 profile 场景）
4. **`list_profiles` 入口预加载**：
   ```python
   flags = (known_flags(db), canonical_flags(db))  # 各 1 次查询
   return [serialize_profile(db, settings, row, flags=flags) for row in profiles]
   ```
   2N 次降到 2 次。

### 边界
- `known_flags` / `canonical_flags` 仍各查一次（非合并）——因二者数据结构不同（set vs dict），合并反而徒增 Python 端转换开销。2 次查询已可接受。
- 单 profile 接口（`get_profile` / `add_profile` / `edit_profile`）不强制改，保持原签名（每次 2 次查询，单 profile 场景可接受）。如需统一可顺带传 flags，但非必须。

---

## 七、模块 D：list_services systemctl 批量化（#8）

### 现状
`llama_services.serialize_service(row, status=True)` → `run_unit_action(row.unit_name, "status")`，N 个服务串行 N 次子进程。

### 设计
1. **新增 `systemd.list_units_status(pattern: str) -> dict[str, CommandResult]`**：
   - 执行 `systemctl list-units 'llamalens-*' --output=json --all --no-pager`
   - 解析 JSON 输出（字段：`unit`、`load`、`active`、`sub`、`description`）
   - 按 `unit` 名建字典，值为轻量 `UnitStatus`（`active`/`sub`/`description`）
   - 命令失败或输出非 JSON 时返回空字典并 `logger.warning("systemctl.list_units_failed")`
2. **`serialize_service` 增加可选参数** `unit_status: dict[str, Any] | None = None`：
   - 传入时从字典取该服务的状态（不再调子进程）
   - 不传入时维持原 `run_unit_action(unit_name, "status")`（单服务详情场景）
3. **`list_services` 在 `with_status=True` 时**：
   ```python
   if with_status:
       status_map = list_units_status("llamalens-*")
   else:
       status_map = None
   return [serialize_service(row, status=with_status, unit_status=status_map) for row in rows]
   ```
4. **`CommandResult` 适配**：`serialize_service` 中 `result["status"]` 的结构保持不变（`ok`/`returncode`/`stdout`/`stderr`），从 `status_map` 派生时 `ok = (active == "active")`、`stdout` 含 sub、`stderr` 为空。

### 边界
- `list-units` 默认只列出 `loaded` + `active`/`inactive` 的单元；加 `--all` 确保 inactive 也列出。归档服务（`archived_at` 非空）默认不查状态（`list_services` 已过滤）。
- 批量查的状态字段粒度可能与单次 `systemctl status` 略有差异（`sub` 状态在 list-units 中也有），前端按 `active`/`sub` 展示即可。
- `list-units` 输出的 `unit` 字段带 `.service` 后缀，与服务表 `unit_name` 一致，可直接 join。

---

## 八、模块 E：下载进度节流 commit（#9）

### 现状
`models_service._run_download` 每 1MB chunk 都 `db.commit()`：
```python
for chunk in response.iter_bytes(1024 * 1024):
    # cancel check ...
    handle.write(chunk)
    written += len(chunk)
    job.downloaded_bytes = written
    db.commit()  # 每 1MB 一次
```

### 设计
1. **双维度节流**：满足"距上次 commit ≥ 2 秒"**或**"距上次 commit ≥ 16MB"时才 commit。
2. **取消检查不节流**：每个 chunk 仍检查 `_cancelled_downloads`，但取消时单独 commit（保证 `cancelled` 态及时落库）。
3. **实现**：
   ```python
   last_commit_at = time.monotonic()
   last_commit_bytes = 0
   COMMIT_INTERVAL_S = 2.0
   COMMIT_INTERVAL_BYTES = 16 * 1024 * 1024

   for chunk in response.iter_bytes(1024 * 1024):
       # cancel check（每 chunk，不节流）
       with _cancel_lock:
           if job_id in _cancelled_downloads:
               job.status = "cancelled"; job.finished_at = ...; db.commit(); cancelled = True; break
       handle.write(chunk)
       written += len(chunk)
       job.downloaded_bytes = written
       now = time.monotonic()
       if (now - last_commit_at >= COMMIT_INTERVAL_S) or (written - last_commit_bytes >= COMMIT_INTERVAL_BYTES):
           db.commit()
           last_commit_at = now
           last_commit_bytes = written
   ```
4. **终态 commit**：循环正常结束后，最终 `db.commit()` 确保最后一段进度落库（再 `part.replace(target)` + `succeeded` + commit）。
5. **配置变量**：`LLAMALENS_DOWNLOAD_COMMIT_INTERVAL_MS`（默认 2000）、`LLAMALENS_DOWNLOAD_COMMIT_INTERVAL_BYTES`（默认 16777216）。

### 边界
- 进程崩溃时丢失最近一次节流窗口内的进度（最多 2 秒或 16MB），但 `.part` 文件保留，重启后由批次 2 的 `_recover_downloads` 标记 `failed` + 清理 `.part`，不影响正确性。
- 取消响应延迟最多一个 chunk（1MB），可接受。

---

## 九、模块 F：列表分页统一（#25）

### 现状
5 个列表接口均无分页：`list_jobs`(limit 200) / `list_profiles` / `list_models` / `list_tasks` / `list_downloads`(limit 100)。

### 设计
1. **统一查询参数**：所有列表接口增加 `offset: int = Query(0, ge=0)`、`limit: int = Query(50, ge=1, le=200)`。
2. **统一返回结构**：
   ```python
   {
     "items": [...],
     "total": <int>,      # 满足筛选条件的总数（不含分页）
     "offset": <int>,
     "limit": <int>,
   }
   ```
3. **total 计算**：对每个列表用 `select(func.count()).select_from(...).where(<同筛选条件>)` 单独查一次总数。筛选条件（如 `task_id` / `q` / `available_only` / `include_archived`）同时作用于 items 与 total。
4. **各接口适配**：
   - `list_jobs`：`task_id` 筛选 + `created_at desc`；total 查同条件。
   - `list_profiles`：`updated_at desc`；无筛选。
   - `list_models`：`q` + `available_only` 筛选；total 查同条件。
   - `list_tasks`：`updated_at desc`；无筛选。
   - `list_downloads`：`created_at desc`；无筛选。
5. **默认 limit/最大 limit**：默认 50、上限 200。`list_jobs` 原 limit 200 改为默认 50（前端分页加载）。
6. **向后兼容**：这是破坏性变更（数组 → 对象），前端必须同步改。

### 前端适配（本批次同步）
5 个列表页改为分页 / 无限滚动：
- `ResultsPage.vue`（benchmarks）：底部分页器 / 滚动加载。
- `ProfilesPage.vue`：分页或按需加载（profile 数量通常不大，可保留全量但走新结构）。
- `ModelsPage.vue`：搜索 + 分页。
- `TasksPage.vue`（任务库，非队列页）：分页。
- `ModelsPage` 的下载列表：分页。

**实现策略**：前端用一个通用 `PaginatedList` 组合式函数或分页器组件，避免重复。本批次不引入完整 API 抽象层（#17 留批次 4），仅在每个页面内联处理 `{items, total, offset, limit}`。

### 边界
- `list_services`（#8）**不纳入分页**：服务数量通常很少（个位数），且 `with_status` 已是本批次优化重点，分页意义不大。
- `list_queue_items`（队列 items）不纳入分页：队列项需完整展示用于排序，且 #6 已优化查询。

---

## 十、配置变量

| 变量 | 默认值 | 作用 |
|---|---|---|
| `LLAMALENS_DOWNLOAD_COMMIT_INTERVAL_MS` | 2000 | 下载进度节流：最小 commit 间隔（毫秒） |
| `LLAMALENS_DOWNLOAD_COMMIT_INTERVAL_BYTES` | 16777216 | 下载进度节流：最小 commit 字节增量（16MB） |

分页 limit 上限（200）与默认（50）硬编码在 `Query` 约束中，不加环境变量。

---

## 十一、安全考量

- **systemctl 批量查询**：`list-units` 的 pattern 固定为 `llamalens-*`，不暴露任意单元状态。解析 JSON 失败时降级为空字典，不抛异常给调用方。
- **下载节流**：取消检查仍每 chunk 执行，不降低取消响应性。节流仅影响 `downloaded_bytes` 落库频率，不影响文件写入正确性。
- **分页 total 查询**：total 与 items 使用相同筛选条件，避免数据不一致。`offset/limit` 有 `ge`/`le` 约束，防恶意大 limit。
- **SQL 注入**：分页用 SQLAlchemy `offset`/`limit` 参数化，`q` 用 `ilike` 参数化，无字符串拼接。

---

## 十二、文件改动清单

### 后端
| 文件 | 改动 |
|---|---|
| `app/api/benchmarks.py` | `_serialize` 加 `lightweight` 参数；`list_jobs` 用 `lightweight=True` + 分页 |
| `app/api/profiles.py` | `list_profiles` 预加载 flags + 分页 |
| `app/api/models.py` | `list_models` / `list_downloads` 分页 |
| `app/api/tasks.py` | `list_tasks` 分页 |
| `app/services/task_queue.py` | `serialize_queue` / `_serialize_item` 批量化；`session_stats` 聚合查询 |
| `app/services/profiles_service.py` | 拆 `_build_argv_with_flags`；`serialize_profile` 加 `flags` 参数；`build_launch_argv` 复用 |
| `app/services/llama_services.py` | `serialize_service` 加 `unit_status` 参数；`list_services` 批量查状态 |
| `app/services/systemd.py` | 新增 `list_units_status(pattern)` |
| `app/services/models_service.py` | `_run_download` 节流 commit |
| `app/schemas.py` | 可选：新增 `PaginatedResponse` 泛型（若用 response_model） |

### 前端
| 文件 | 改动 |
|---|---|
| `src/views/ResultsPage.vue` | 适配 `{items,total,offset,limit}` + 分页 UI |
| `src/views/ProfilesPage.vue` | 适配新结构 + 分页 |
| `src/views/ModelsPage.vue` | 适配新结构（模型列表 + 下载列表）+ 分页 |
| `src/views/TasksPage.vue` | 任务库列表适配新结构 + 分页（队列轮询部分不改） |
| `src/composables/usePagination.ts`（新增） | 通用分页组合式函数 |

### 测试
| 文件 | 改动 |
|---|---|
| `tests/test_benchmark.py` | `list_jobs` 轻量化 + 分页断言 |
| `tests/test_profiles.py` | `list_profiles` flags 复用 + 分页断言 |
| `tests/test_services.py` | `list_services?with_status=true` 批量查 mock + 分页断言 |
| `tests/test_task_queue.py` | `serialize_queue` 批量化断言（查询计数） |
| `tests/test_models_service.py`（新增或扩展） | 下载节流 commit 断言 |

---

## 十三、依赖变更

无新增依赖。全部使用标准库 + 现有 SQLAlchemy / FastAPI 能力。

---

## 十四、验证计划

### 单元测试
1. **#5**：构造 200 个含 attempts 的 job，`list_jobs` 断言不触发 attempts 懒加载（可用 `session.no_autoflush` 或查询计数）；返回的 metrics 与 `summary_json` 一致。
2. **#6**：`serialize_queue` 在 N 个队列项下，断言 SQL 查询数为常数（用 `pytest-sql` 或 mock `db.scalars` 计数）；`session_stats` 与逐行计数结果一致。
3. **#7**：`list_profiles` 在 N 个 profile 下，断言 `ArgumentCatalog` 查询数为 2（非 2N）。
4. **#8**：mock `subprocess.run` 返回 `list-units` JSON，断言 `list_services?with_status=true` 只调一次子进程；join 结果正确。
5. **#9**：mock `httpx.stream` 产出大量 chunk，断言 `db.commit` 次数为 `ceil(total / 16MB) + ceil(total_time / 2s)` 量级，非 chunk 数。
6. **#25**：各列表接口 `offset/limit` 边界、`total` 与 items 一致性。

### 回归
- `pytest backend/tests` 全量通过
- `npm run build`（含 vue-tsc）通过
- VS Code 诊断无错误

### 性能验证（可选）
- 构造 200 个 job + 20 个队列项，对比批次前后 `list_jobs` / `GET /queue` 的 SQL 查询数与响应时间。

---

## 十五、实施顺序

1. **模块 A（#5）**：`_serialize` 轻量化——最简单，先做。
2. **模块 B（#6）**：`serialize_queue` 批量化——独立，可单独验证。
3. **模块 C（#7）**：`list_profiles` flags 复用——涉及 `profiles_service` 签名调整。
4. **模块 D（#8）**：`list_services` 批量 systemctl——涉及 `systemd.py` 新增函数。
5. **模块 E（#9）**：下载节流——独立，可单独验证。
6. **模块 F（#25）**：分页 + 前端适配——最后做，因前端改动依赖前 5 个接口稳定。先改后端 5 个接口返回结构，再改前端 5 个页面。

> 模块 A-E 互不依赖，可并行；模块 F 的后端部分依赖 A-E 的接口已稳定（避免返工），前端部分在 F 后端完成后进行。

---

## 十六、范围边界（明确不做）

- **不**引入前端 API 抽象层（#17，批次 4）：前端仍直接 `api<T>('/benchmarks?offset=0&limit=50')` 内联拼。
- **不**引入 SSE 推送（#10，批次 4）：队列仍轮询，但 #6 已降低每次轮询开销。
- **不**改 `list_services` 分页：服务数量少，且 #8 已优化。
- **不**改队列 items 分页：需完整展示用于排序。
- **不**加进程内缓存（#7）：按用户确认，每请求查一次即可。
- **不**改单 profile / 单 job 接口的 flags / attempts 加载：单实体场景开销可接受。
