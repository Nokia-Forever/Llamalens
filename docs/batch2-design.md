# LlamaLens 批次 2 设计文档：队列系统加固（孤儿回收 + 调度异常保护 + 并发写锁 + 停止语义）

> 本文档是 **设计阶段**，不含最终实现代码。对应 `optimization-plan.md` 的批次 2（#2 / #4 / #14 / #15）。
> 依赖批次 1 已交付的结构化日志（`logger.exception` 可用）、认证中间件、`/ready` 探针与 `QueueScheduler.is_alive()`。
> 关键决策已于评审中确认（见 §三），文末列出“不在批次 2 范围”的项，避免与批次 3+ 冲突。

---

## 一、本设计解决什么问题

批次 2 聚焦“队列状态机 / 生命周期 / 后台线程”这一后端最易出 bug 的区域。四个问题都集中在 `task_queue.py` 与其周边，连续改一处即可改透：

### 问题 A（#2）：孤儿任务回收不完整

- `recover_on_startup()`（[task_queue.py:267-291](file:///d:/user/worker/LlamaLens/backend/app/services/task_queue.py#L267-L291)）只回收**队列内**的 `current_item_id`：把它关联的 `BenchmarkJob` 置 `failed`、删除 `TaskQueueItem`、队列置 `idle`。
- **队列之外**直接创建的 Benchmark 不会被回收：`create_benchmark_job` 经 `BENCHMARK_EXECUTOR.submit(_run_job, ...)` 在后台执行（[benchmark.py:98-116](file:///d:/user/worker/LlamaLens/backend/app/services/benchmark.py#L98-L116)），重启后其 `BenchmarkJob` 仍卡在 `running`/`queued`。
- 下载任务同样卡死：`models_service.EXECUTOR.submit(_run_download, ...)`（[models_service.py:120-136](file:///d:/user/worker/LlamaLens/backend/app/services/models_service.py#L120-L136)），重启后 `DownloadJob` 仍卡在 `running`/`queued`。
- 且 `_cancelled_downloads`（[models_service.py:25](file:///d:/user/worker/LlamaLens/backend/app/services/models_service.py#L25)）与 `_cancelled_jobs`（[benchmark.py:31](file:///d:/user/worker/LlamaLens/backend/app/services/benchmark.py#L31)）是**内存集合**，重启即丢失——虽无 job 可取消（已被回收标记失败），但残留 `.part` 文件会阻塞下次下载（`create_download` 检测 `.part` 存在即拒绝，[models_service.py:129](file:///d:/user/worker/LlamaLens/backend/app/services/models_service.py#L129)）。

### 问题 B（#4）：调度线程静默吞异常

- `QueueScheduler._loop`（[task_queue.py:318-325](file:///d:/user/worker/LlamaLens/backend/app/services/task_queue.py#L318-L325)）：
  ```python
  except Exception:
      pass
  ```
- 若 `_tick()` 因 SQLite `database is locked`、代码 bug 反复失败，会**无限空转且无任何日志**，故障完全不可见（批次 1 仅接入正常事件日志，明确不改此 `except`，留待本批次）。
- 无连续失败计数、无 `error` 态、API 无法暴露调度器健康细节，`/ready` 仅能判断线程存活，无法判断“线程活着但反复报错”。

### 问题 C（#14）：队列并发写入无显式锁

- `QueueScheduler` 使用独立 `SessionLocal`（`_tick` 内 `db = SessionLocal()`，[task_queue.py:329](file:///d:/user/worker/LlamaLens/backend/app/services/task_queue.py#L329)），API 请求使用请求级 session（`get_db`，[database.py:121](file:///d:/user/worker/LlamaLens/backend/app/database.py#L121)），二者并发写 `TaskQueue` / `TaskQueueItem`。
- SQLite 默认隔离下，并发 commit 可能抛 `database is locked`（引擎虽开 WAL，但未设 `busy_timeout`，[database.py:28-34](file:///d:/user/worker/LlamaLens/backend/app/database.py#L28-L34)）。
- `enqueue_item` 的 `head` 分支逐条 `order_index += 1`（[task_queue.py:188-196](file:///d:/user/worker/LlamaLens/backend/app/services/task_queue.py#L188-L196)）期间，scheduler 可能正在 dispatch，产生交错。

### 问题 D（#15）：`stopping` 语义反直觉

- `delete_item` 删除当前运行项时置 `q.status = "stopping"` 并 `cancel_benchmark`（[task_queue.py:244-258](file:///d:/user/worker/LlamaLens/backend/app/services/task_queue.py#L244-L258)）。
- 但 `_handle_run_finished` 在运行结束后，若仍有 `waiting` 项，会把状态**回到 `running`** 继续执行后续任务（[task_queue.py:449-451](file:///d:/user/worker/LlamaLens/backend/app/services/task_queue.py#L449-L451)）。
- 用户点“停止并删除”期望整队停下，实际却继续跑下一个——语义与直觉不符。当前 `TasksPage` 仅有“暂停/停止并删除”，无独立的“停止整队”操作（[TasksPage.vue:261-264](file:///d:/user/worker/LlamaLens/frontend/src/views/TasksPage.vue#L261-L264)）。

---

## 二、目标与非目标

### 目标
1. **统一孤儿回收**：启动时扫描全部 `running`/`queued` 的 `BenchmarkJob`（含队列内与 standalone）与 `DownloadJob`，标记 `failed` + `interrupted by restart`，并清理下载残留 `.part` 文件。
2. **调度异常可见 + 失败保护**：`_loop` 不再静默吞异常；连续失败超阈值时队列置 `error` 态，停止 dispatch，在 `/queue` 与 `/ready` 暴露失败计数与最近错误；提供“自动退避重试 + 手动复位”双路径恢复。
3. **并发写串行化**：引入进程内 `threading.Lock` 串行化队列状态变更（enqueue / reorder / delete / dispatch / stop / reset），**长任务执行不持锁**；附带补 `busy_timeout` 作为跨会话防御。
4. **停止语义明确**：保留“停止当前任务”（停当前 + 删除当前项 + 队列继续后续）；新增“停止队列”（停当前 + 当前项回到队首 waiting + 整队置 idle，保留剩余任务待恢复）；新增 error 态下的“复位队列”。

### 非目标（明确不在批次 2）
- #6 `serialize_queue` 的 N+1 批量加载、`session_stats` 聚合查询 → 批次 3（性能）。
- #10 队列 idle 慢轮询 / SSE 推送 → 批次 3/4（SSE 依赖本批次的 scheduler 状态扩展，但推送本身不在本批次）。
- #11 Alembic 迁移、#12 拆分 `task_queue.py` → 批次 5。本批次**不新增数据表、不加列**（`error` 态复用 `TaskQueue.status` 字符串，计数/最近错误存内存），避免触发迁移。
- #16 Excel Web Worker、#22 SSE、#25 分页、Prometheus 指标 → 各自后续批次。

---

## 三、关键设计决策（已确认）

| 维度 | 决策 | 理由 |
|---|---|---|
| 停止语义（#15） | **保留“停止当前任务” + 新增“停止队列”** | “停止当前任务”：停当前 + 删除当前项 + 队列继续后续（沿用 `delete_item` 现有行为，仅改文案）。新增“停止队列”：停当前 + 当前项回到队首 `waiting` + 整队置 `idle`，保留剩余任务待 `PATCH {status:"start"}` 恢复。两者用不同 status 值区分。符合 plan“补充独立停止整队操作”的建议。 |
| 并发锁（#14） | **进程内 `threading.Lock`** | 一把模块级锁串行化全部队列状态变更；`run_benchmark_job` 长任务在锁外执行。低风险、符合 plan 主建议；附带 `PRAGMA busy_timeout` 作为跨会话/边缘并发的二道防线。 |
| 错误态恢复（#4） | **自动退避 + 手动复位 两者皆有** | 瞬时故障（如短暂 DB 锁）由 30s 退避自动重试恢复；持续故障经日志暴露后由运维 `POST /queue/reset` 手动复位。阈值默认 5 次，可配置。 |
| `error` 态存储 | **`status` 字段串值 + 内存计数** | `TaskQueue.status` 增加 `"error"` 取值（字符串列无需迁移）；`consecutive_failures` / `last_error` / `last_error_at` 存 `QueueScheduler` 内存（单进程单线程，重启由回收复位）。避免加列与迁移。 |

---

## 四、模块 A：统一孤儿任务回收（#2）

### 4.1 回收总入口

保留 `recover_on_startup()` 作为 lifespan 唯一调用点（[main.py:40](file:///d:/user/worker/LlamaLens/backend/app/main.py#L40)），在 `init_db()` / seed / migrate / token bootstrap 之后、`get_scheduler().start()` 之前执行。内部重构为三个步骤，共用一个 session，逐步提交（部分进展亦持久化，避免中途失败回滚已恢复项）：

```
def recover_on_startup() -> None:
    db = SessionLocal()
    try:
        _recover_queue_current_item(db)   # 既有的队列内回收（保留行为）
        _recover_standalone_benchmarks(db)  # 新增
        _recover_downloads(db)            # 新增
    finally:
        db.close()
```

### 4.2 步骤 1：队列当前项回收（既有，保留）

- 读 `q.current_item_id`；若非空，取其 `last_run_id` 对应 `BenchmarkJob`，若 `status in ('queued','running')` 则置 `failed`、`error="interrupted by restart"`、`finished_at=now`，并 `_update_task_stats(..., "failed")`。
- `_record_history(..., "canceled", ..., {"reason":"restart"})`，删除该 `TaskQueueItem`，`q.current_item_id=None`。
- `q.status="idle"`；若 `next_dispatch_at` 已过期则清空。
- `db.commit()`。

> 行为与现状一致，仅提取为独立函数以便复用 session 与日志。

### 4.3 步骤 2：standalone Benchmark 回收（新增）

- 扫描所有 `BenchmarkJob` 中 `status in ('running','queued')`（**不**按 `queue_session_id` 过滤——队列当前项的 job 已在步骤 1 被置 `failed`，此处不会重复命中；扫描全部更稳健，覆盖任何遗漏）。
- 逐条置 `failed`、`error="interrupted by restart"`、`finished_at=now`。
- `db.commit()`。
- `logger.warning("benchmark.recovered", extra={"count": n})`。

### 4.4 步骤 3：下载任务回收（新增）

- 扫描所有 `DownloadJob` 中 `status in ('running','queued')`。
- 逐条置 `failed`、`error="interrupted by restart"`、`finished_at=now`。
- **清理残留 `.part` 文件**：对每条恢复的下载，计算 `part_path = Path(target_path).with_suffix(suffix + ".part")`（与 `_run_download` 的 `.part` 命名一致，[models_service.py:157](file:///d:/user/worker/LlamaLens/backend/app/services/models_service.py#L157)），`unlink(missing_ok=True)`；逐文件 `try/except` 并 `logger.warning("download.part_cleanup_failed", ...)`，不中断整体回收。
- `db.commit()`。
- `logger.warning("download.recovered", extra={"count": n})`。

### 4.5 内存取消集合

- `_cancelled_jobs` / `_cancelled_downloads` 重启后为空。由于所有运行中 job 已被回收标记失败，不存在“需取消但取消信号丢失”的活任务。**无需持久化**，仅在本设计文档说明此结论。

### 4.6 日志事件

| 事件 | 级别 | 上下文 |
|---|---|---|
| `benchmark.recovered` | WARNING | `count` |
| `download.recovered` | WARNING | `count` |
| `download.part_cleanup_failed` | WARNING | `job_id`, `error` |

---

## 五、模块 B：调度线程异常日志 + 失败保护（#4）

### 5.1 状态机扩展

`TaskQueue.status` 在原有 `idle / running / paused / stopping` 之外增加：

| 取值 | 含义 | 进入 | 退出 |
|---|---|---|---|
| `error` | 调度器连续失败超阈值，已停止 dispatch，等待退避重试或手动复位 | `_handle_tick_failure` 计数达阈值 | 自动重试成功 → `running`/`idle`；或 `POST /queue/reset` → `idle` |

> 新增 `stopping_queue` 见 §七（#15）。

### 5.2 `QueueScheduler` 内存诊断字段

新增实例字段（不持久化，重启由回收复位）：

```
self._consecutive_failures = 0
self._last_error: str | None = None
self._last_error_at: datetime | None = None
```

提供 `diagnostics() -> dict`：`{"consecutive_failures": int, "last_error": str|None, "last_error_at": datetime|None}`。

### 5.3 `_loop` 改造

```
def _loop(self) -> None:
    while self._running:
        try:
            self._tick()
            self._on_tick_success()
        except Exception:
            self._handle_tick_failure()
        with self._condition:
            in_error = self._consecutive_failures >= self._failure_threshold
            wait_s = (self._error_cooldown_s) if in_error else 1.0
            self._condition.wait(timeout=wait_s)
```

要点：
- **不再 `pass`**：`except Exception` 调 `_handle_tick_failure()`，内部 `logger.exception("queue.tick_failed", extra={"consecutive_failures": n})`。
- **成功即复位**：`_on_tick_success()` 将 `_consecutive_failures` 置 0；若 DB 中 `q.status == "error"`，则**乐观恢复**为 `running`（若无 waiting 项，`_tick` 内 `_try_dispatch` 会自然落回 `idle`），并清 `_last_error` / `_last_error_at`，记 `queue.error_recovered`。
- **退避等待**：进入 `error` 区间后，循环等待 `error_cooldown_s`（默认 30s）再重试，避免空转打满 CPU / 日志。

### 5.4 `_handle_tick_failure` 流程

```
def _handle_tick_failure(self) -> None:
    self._consecutive_failures += 1
    self._last_error = _format_error(exc)
    self._last_error_at = now_utc()
    logger.exception("queue.tick_failed", extra={
        "consecutive_failures": self._consecutive_failures,
    })
    if self._consecutive_failures >= self._failure_threshold:
        _persist_error_state()   # 新建 session：q.status="error", commit
        logger.error("queue.error_state_entered", extra={
            "consecutive_failures": self._consecutive_failures,
            "threshold": self._failure_threshold,
        })
```

- `_persist_error_state` 用独立 `SessionLocal()`（与 `_tick` 的 session 隔离），仅置 `q.status="error"` 并 commit；置位前若已是 `error` 则幂等。
- 持久化 `error` 后，下一次 `_tick`：若 `q.status not in ("running","stopping")` 会提前 return（[task_queue.py:332](file:///d:/user/worker/LlamaLens/backend/app/services/task_queue.py#L332)），**不会**误把提前 return 当作成功复位——`_on_tick_success` 仅在 `_tick` 未抛异常时调用，而 `error` 态下 `_tick` 提前 return 也不抛异常，会导致计数误清。

> **关键修正**：为避免“error 态下 `_tick` 提前 return → `_on_tick_success` 误清计数 → 永不复位”的死锁，`_on_tick_success` 仅在“本次 `_tick` 真正执行了 dispatch / finish 路径”时才复位。实现上：`_tick` 进入 `running/stopping` 分支并完成（无论是否真的 dispatch）即视为成功；若因 `error`/`idle`/`paused` 提前 return，则**不调用** `_on_tick_success`。具体做法：把“是否执行了实质工作”作为 `_tick` 的返回值（`bool`），`_loop` 据此决定是否复位计数。

```
def _loop(self) -> None:
    while self._running:
        try:
            did_work = self._tick()      # 返回是否进入实质分支
            if did_work:
                self._on_tick_success()
        except Exception:
            self._handle_tick_failure()
        ...
```

### 5.5 自动恢复与手动恢复（两者皆有）

- **自动（退避）**：`error` 态下循环每 `error_cooldown_s` 秒醒来重试 `_tick`；瞬时故障恢复后自动复位并继续。
- **手动（复位）**：新增 `POST /api/v1/queue/reset`（见 §七），置 `q.status="idle"`，并经 scheduler 清内存计数/`last_error`。用户随后 `PATCH {status:"start"}` 恢复。
- 持续故障下：每 30s 重试一次，每次记一条 `queue.tick_failed`，队列保持 `error`，运维据日志定位根因后手动复位。

### 5.6 API 暴露

- `GET /queue` 返回的 `serialize_queue` 附加 `scheduler` 节：`get_scheduler().diagnostics()`。
- `GET /ready`（批次 1 已有 `db` / `scheduler_alive`）扩展 `checks`：
  - `queue_status`: `q.status`
  - `scheduler_failures`: `consecutive_failures`
- `queue_status == "error"` 或 `scheduler_failures > 0` 时 `/ready` 的 `status` 为 `degraded`。

### 5.7 日志事件

| 事件 | 级别 | 上下文 |
|---|---|---|
| `queue.tick_failed` | ERROR | `consecutive_failures`, `exc_info` |
| `queue.error_state_entered` | ERROR | `consecutive_failures`, `threshold` |
| `queue.error_recovered` | INFO | `consecutive_failures`(0) |
| `queue.reset` | INFO | `prev_status` |

---

## 六、模块 C：队列并发写锁（#14）

### 6.1 锁的位置与粒度

新增模块级 `_queue_lock = threading.Lock()`（`task_queue.py`）。**一把锁**串行化以下“状态读-改-写”临界区：

| 函数 | 临界区 | 锁外 |
|---|---|---|
| `start_queue` / `pause_queue` / `update_queue_settings` | 读改 `q.status` / 设置 + commit | `get_scheduler().notify()` |
| `enqueue_item` | order_index 平移 + 插入 item + history + commit | `notify()` |
| `reorder_items` | 校验 + 重排 order_index + history + commit | `notify()` |
| `delete_item` | 读改 `q`/`item` + history + commit | `cancel_benchmark(last_run_id)`、`notify()` |
| `stop_queue`（新） | 读改 `q.status` + commit | `cancel_benchmark`、`notify()` |
| `reset_queue`（新） | 置 `q.status=idle` + 清诊断 + commit | `notify()` |
| `QueueScheduler._try_dispatch` | 选 waiting 首项 + 建 job + 置 item running + history + commit | — |
| `QueueScheduler._handle_run_finished` | 读 job 结果 + 删/重排 item + 置 q + history + commit | — |

### 6.2 关键不变量：长任务不持锁

`_tick` 的结构保持不变（[task_queue.py:327-354](file:///d:/user/worker/LlamaLens/backend/app/services/task_queue.py#L327-L354)）：dispatch / handle_finished 各自短临界区持锁，**中间 `run_benchmark_job(job_id)` 不持锁**：

```
def _tick(self) -> bool:
    job_id = None
    db = SessionLocal()
    try:
        with _queue_lock:
            q = _ensure_queue_row(db)
            if q.status not in ("running", "stopping"):
                return False   # 未做实质工作
            if q.current_item_id is None and q.status == "running":
                self._try_dispatch(db, q)        # 持锁内
            if q.current_item_id is not None:
                item = db.get(...)
                job_id = item.last_run_id if item else None
    finally:
        db.close()

    if job_id:
        run_benchmark_job(job_id)                # 锁外，长任务
        db = SessionLocal()
        try:
            with _queue_lock:
                q = db.get(TaskQueue, 1)
                if q and q.current_item_id is not None:
                    self._handle_run_finished(db, q)   # 持锁内
        finally:
            db.close()
        self.notify()
    return True
```

> `run_benchmark_job` 期间锁已释放，API 的 `enqueue_item` / `delete_item` 仍可安全操作（仅动 `waiting` 项或置 `stopping`），不会与即将到来的 `_handle_run_finished` 交错——后者会再次取锁。

### 6.3 锁与 `EXECUTION_LOCK` 的关系

`benchmark._run_job` 用 `EXECUTION_LOCK`（[benchmark.py:624](file:///d:/user/worker/LlamaLens/backend/app/services/benchmark.py#L624)）串行化对 llama-server 的访问；`_queue_lock` 串行化**队列状态机**。二者层级不同、互不嵌套，无死锁风险（`_queue_lock` 永不在 `EXECUTION_LOCK` 内获取，反之亦然）。

### 6.4 `busy_timeout` 防御（附带）

在 `_configure_sqlite`（[database.py:28-34](file:///d:/user/worker/LlamaLens/backend/app/database.py#L28-L34)）的 PRAGMA 序列追加：

```
cursor.execute("PRAGMA busy_timeout=5000")
```

理由：`_queue_lock` 覆盖进程内并发；`busy_timeout` 作为跨会话/极端并发的二道防线，使短暂锁等待自动重试而非立即抛 `database is locked`。无新依赖。

### 6.5 不采用 `BEGIN IMMEDIATE` / 单写者架构的理由

- `BEGIN IMMEDIATE` 需改 session 事务模式与隔离级别，影响面大（所有写路径），与 `threading.Lock` 收益重叠。
- 单写者（scheduler 为唯一写者，API 投递事件）最干净，但属架构级重构，留待批次 5（#12 拆分 `task_queue.py` 时一并）。

---

## 七、模块 D：停止语义明确化 + 停止/复位队列操作（#15）

### 7.1 语义对照表

| 操作 | 入口 | 当前项处理 | 运行结束后队列状态 | 剩余 waiting 项 |
|---|---|---|---|---|
| 停止当前任务（既有，改文案） | `DELETE /queue/items/{id}`（current） | `stopping` → 取消运行 → `_handle_run_finished` **删除当前项** | `running`（若有 waiting）或 `idle` | 保留，继续执行 |
| 停止队列（新增） | `PATCH /queue {status:"stop"}` | `stopping_queue` → 取消运行 → `_handle_run_finished` **当前项回到队首 `waiting`** | `idle` | 保留，待恢复 |
| 暂停（既有） | `PATCH /queue {status:"pause"}` | 不动当前项，等当前跑完 | `paused` | 保留 |
| 复位队列（新增） | `POST /queue/reset` | 仅在 `error` 态可用；置 `idle` + 清诊断 | `idle` | 保留 |

### 7.2 新增 status 取值

- `stopping_queue`：停止整队的瞬态（取消当前运行中）；`_handle_run_finished` 见此值 → 当前项回 `waiting`、`q.status=idle`。
- `error`：见 §五。

无需迁移：`TaskQueue.status` 为 `String(32)`，新值仅是字符串取值扩展。

### 7.3 `stop_queue` 服务函数

```
def stop_queue(db: Session) -> dict:
    with _queue_lock:
        q = _ensure_queue_row(db)
        if q.status not in ("running", "stopping"):
            raise ValueError(f"队列当前状态为 {q.status}，无法停止")
        q.status = "stopping_queue"
        last_run_id = None
        if q.current_item_id:
            item = db.get(TaskQueueItem, q.current_item_id)
            if item and item.last_run_id:
                last_run_id = item.last_run_id
        _record_history(db, q.current_item_id, "", "stop_queue", detail={})
        db.commit()
    if last_run_id:
        cancel_benchmark(last_run_id)    # 锁外
    get_scheduler().notify()
    return serialize_queue(db, q)
```

### 7.4 `_handle_run_finished` 分支扩展

在既有“删除当前项 + 据 `stopping` 决定 running/idle”逻辑前增加 `stopping_queue` 分支：

```
if q.status == "stopping_queue":
    # 当前项回到队首 waiting，整队置 idle
    item.status = "waiting"
    item.started_at = None
    item.last_run_id = None          # 等待下次 dispatch 重新创建 run
    q.current_item_id = None
    q.status = "idle"
    q.next_dispatch_at = None
    _record_history(..., "canceled", ..., {"reason": "stop_queue"})
else:
    db.delete(item)                  # 既有：删除当前项
    q.current_item_id = None
    if q.status == "stopping":
        q.status = "running" if waiting_count > 0 else "idle"
    else:
        q.status = "idle" if waiting_count == 0 else q.status
        q.next_dispatch_at = (now + interval) if waiting_count > 0 and interval>0 else None
```

> 当前项 `order_index` 保持原值（被 dispatch 时未改），自然位于队首；恢复后 `PATCH {status:"start"}` 会从队首重新 dispatch。

### 7.5 `reset_queue` 服务函数（error 态专用）

```
def reset_queue(db: Session) -> dict:
    with _queue_lock:
        q = _ensure_queue_row(db)
        prev = q.status
        if q.status != "error":
            raise ValueError(f"队列当前状态为 {q.status}，仅 error 态可复位")
        q.status = "idle"
        q.current_item_id = q.current_item_id  # 不动
        db.commit()
    sched = get_scheduler()
    sched._consecutive_failures = 0
    sched._last_error = None
    sched._last_error_at = None
    logger.info("queue.reset", extra={"prev_status": prev})
    get_scheduler().notify()
    return serialize_queue(db, q)
```

### 7.6 API 变更

| 方法 | 路径 | 入参 | 行为 |
|---|---|---|---|
| PATCH | `/queue` | `QueuePatch.status` 增加 `"stop"` | `"stop"` → `stop_queue`；`"start"`/`"pause"` 既有 |
| POST | `/queue/reset` | — | `reset_queue`；非 `error` 态返回 409 |

`QueuePatch.status` 类型扩展为 `Literal["start", "pause", "stop"]`（[schemas.py:186](file:///d:/user/worker/LlamaLens/backend/app/schemas.py#L186)）。

### 7.7 前端变更（`TasksPage.vue` / `types.ts`）

- `TaskQueueState.status` 增加 `'stopping_queue' | 'error'`（[types.ts:160](file:///d:/user/worker/LlamaLens/frontend/src/types.ts#L160)）。
- 控制区按钮：
  - `running` 时显示“停止队列”（`PATCH {status:"stop"}`）。
  - `error` 时显示“复位队列”（`POST /queue/reset`）。
  - `stopping_queue` 时显示“停止队列中…”（disabled）。
- 当前运行卡片按钮文案“停止并删除” → “停止当前任务”（行为不变）。
- `queue-status-badge` 增加 `qs-stopping_queue` / `qs-error` 样式。
- 队列状态区显示 `scheduler.last_error`（若有）。

---

## 八、配置与环境变量变更

| 变量 | 默认 | 作用 |
|---|---|---|
| `LLAMALENS_QUEUE_FAILURE_THRESHOLD` | `5` | 连续失败超此值置 `error` 态 |
| `LLAMALENS_QUEUE_ERROR_COOLDOWN_MS` | `30000` | `error` 态退避重试间隔（毫秒） |

> 阈值与退避均可在文档/部署说明中标注为可配置；默认值保守，避免瞬时抖动即停摆。

---

## 九、安全考量

1. **锁不跨进程**：`threading.Lock` 仅保护单进程内并发（uvicorn 默认单 worker 足够）；多 worker 部署不在本批次支持范围（README 已隐含单进程）。`busy_timeout` 提供跨会话边缘保护。
2. **复位需鉴权**：`POST /queue/reset` 挂在已有 `verify_auth` 依赖下（批次 1），loopback 默认免认证仍适用。
3. **错误信息脱敏**：`last_error` 仅记异常类型+消息（`f"{type(exc).__name__}: {exc}"`），不包含令牌/路径等敏感字段；`logger.exception` 栈中若含敏感信息由调用方负责（现有 benchmark/download 路径已脱敏 URL，批次 1 确认）。
4. **`.part` 清理范围**：仅删除本次恢复的 `DownloadJob.target_path` 对应 `.part`，不递归、不遍历目录，避免误删。
5. **回收幂等**：所有回收步骤对已是 `failed` 的 job 跳过（`status in ('running','queued')` 过滤），重复执行安全。

---

## 十、文件改动清单（设计层面，不含实现）

### 后端修改
- `backend/app/services/task_queue.py`
  - `recover_on_startup` 重构为三步回收（队列项 / standalone benchmark / download）。
  - `QueueScheduler`：内存诊断字段 + `diagnostics()`；`_loop` 去 `pass` + 计数 + 退避 + 乐观恢复；`_handle_tick_failure` / `_on_tick_success` / `_persist_error_state`；`_tick` 返回 `did_work`。
  - 模块级 `_queue_lock`，包裹 `start_queue/pause_queue/update_queue_settings/enqueue_item/reorder_items/delete_item` 临界区；`_try_dispatch`/`_handle_run_finished` 持锁。
  - 新增 `stop_queue` / `reset_queue`；`_handle_run_finished` 增加 `stopping_queue` 分支。
  - `serialize_queue` 附加 `scheduler` 诊断节。
- `backend/app/api/queue.py`
  - `patch_queue` 处理 `status=="stop"`；新增 `POST /queue/reset` 路由。
- `backend/app/schemas.py`
  - `QueuePatch.status` 扩展为 `Literal["start", "pause", "stop"]`。
- `backend/app/main.py`
  - `/ready` 扩展 `checks.queue_status` / `checks.scheduler_failures`，`error` 态或 `failures>0` 时 `status="degraded"`。
- `backend/app/database.py`
  - `_configure_sqlite` 增加 `PRAGMA busy_timeout=5000`。
- `backend/app/services/benchmark.py`
  - `create_benchmark_job` / `_run_job` 无逻辑改动；回收由 `task_queue.recover_on_startup` 统一处理（仅依赖其 `BenchmarkJob` 模型）。
- `backend/app/services/models_service.py`
  - 无逻辑改动；下载回收与 `.part` 清理由 `task_queue.recover_on_startup` 统一处理（仅依赖其 `DownloadJob` 模型与 `.part` 命名约定）。

### 前端修改
- `frontend/src/types.ts`：`TaskQueueState.status` 增加 `'stopping_queue' | 'error'`；增加 `scheduler` 诊断字段类型。
- `frontend/src/views/TasksPage.vue`：新增“停止队列”/“复位队列”按钮与状态样式；当前运行卡片按钮文案改为“停止当前任务”；显示 `last_error`。

### 后端新增（文件）
- 无新文件（沿用 `task_queue.py` / `queue.py` / `schemas.py`）。

### 测试新增
- `backend/tests/test_task_queue.py`（新建）：
  - 孤儿回收：插 `running` benchmark + `running` download + 队列 current_item，调 `recover_on_startup`，断言全 `failed` + `.part` 被删。
  - 调度异常：mock `_tick` 抛异常，断言 `queue.tick_failed` 日志、计数递增、达阈值后 `q.status="error"`、`/ready` 为 `degraded`、`/queue` 暴露 `scheduler.consecutive_failures`。
  - 自动恢复：阈值后 mock `_tick` 恢复成功，断言 `q.status` 回 `running`/`idle`、计数清零。
  - 手动复位：`error` 态 `POST /queue/reset` → `idle`；非 `error` 态 → 409。
  - 停止语义：`stop_queue` 后 `stopping_queue` → 模拟 run 结束 → 当前项回 `waiting`、`q.status="idle"`；`delete_item` 当前项 → `stopping` → run 结束 → 删除当前项、`q.status="running"`。
  - 并发锁：`enqueue_item` 的 `head` 平移与 `_try_dispatch` 在锁下串行（可用 `threading.Barrier` 制造竞争，断言无 `database is locked`）。

---

## 十一、依赖变更
- 后端无新增三方依赖（`threading` / `logging` / `pathlib` 均标准库）。
- 前端无新增依赖。

---

## 十二、兼容性与回滚
- `recover_on_startup` 扩展为向后兼容：无 running/queued job 时等同现状。
- `error` / `stopping_queue` 是新增 status 取值，旧前端读到会原样显示字符串（不致崩），更新前端后展示正常。
- `_queue_lock` / `busy_timeout` 对正常流程无行为改变，仅串行化临界区。
- 回滚：移除 `stop_queue`/`reset_queue` 与新增 status、还原 `_loop` 的 `except`、卸载锁与 `busy_timeout`，即回到批次 1 状态。
- 现有 `pytest` 用例保持绿（`conftest.py` 每 case 重建库；`client` fixture 触发 lifespan，回收在空库上为空操作）。

---

## 十三、验证计划（实现后执行）
1. `python -m pytest backend/tests` 全绿（含新增 `test_task_queue.py`）。
2. `cd frontend && npm run build` 通过（含 `vue-tsc`）。
3. 手动：
   - **回收**：构造 `running` benchmark + `running` download + 残留 `.part`，重启服务，确认均 `failed`（`interrupted by restart`）、`.part` 被删、日志有 `benchmark.recovered`/`download.recovered`。
   - **异常保护**：注入 `_tick` 故障（如临时改 `_try_dispatch` 抛错），确认 5 次后 `q.status="error"`、`/ready` 为 `degraded`、`/queue` 返回 `scheduler.consecutive_failures`/`last_error`；30s 后自动恢复（瞬时故障）。
   - **手动复位**：`error` 态 `POST /queue/reset` → `idle`；非 `error` 态 → 409。
   - **停止队列**：队列运行中 `PATCH {status:"stop"}`，确认当前项回队首 `waiting`、`q.status="idle"`、剩余项保留；`PATCH {status:"start"}` 恢复后从队首重跑。
   - **停止当前任务**：当前运行项“停止当前任务”，确认该项被删、队列继续后续。
   - **并发**：快速连续 `enqueue head` + 启动队列，确认无 `database is locked`、order_index 无错乱。

---

## 十四、批次 2 内部实施顺序
1. **模块 C（并发锁）**：先加 `_queue_lock` + `busy_timeout`，建立串行化基座，后续改动都在锁下进行，降低竞态回归面。
2. **模块 B（异常保护）**：改造 `_loop` / `_tick` 返回值 / 失败计数 / `error` 态 / 退避 / 诊断暴露 / `/ready` 扩展。
3. **模块 D（停止语义）**：新增 `stopping_queue` / `stop_queue` / `reset_queue` / `_handle_run_finished` 分支 / API / 前端按钮。
4. **模块 A（孤儿回收）**：扩展 `recover_on_startup` 三步回收 + `.part` 清理 + 日志。
5. **测试**：贯穿每步，最后 `test_task_queue.py` 整体回归。

每个子步骤后回归：`pytest backend/tests` + `npm run build`。

---

## 十五、显式不在批次 2 范围（避免与批次 3+ 冲突）
- #6 `serialize_queue` N+1 批量加载、`session_stats` 聚合查询 → 批次 3（本批次仅给 `serialize_queue` 附加内存诊断节，不动 items/session_stats 查询）。
- #10 队列 idle 慢轮询 / SSE 推送 → 批次 3/4（SSE 可复用本批次的 `error`/诊断扩展，但推送通道不在本批次）。
- #11 Alembic 迁移 → 批次 5（本批次不加列、不加表，规避迁移）。
- #12 拆分 `task_queue.py` → 批次 5（本批次在原文件内演进）。
- #15 的“停止队列是否清空剩余项”扩展、`stop_queue` 在 `paused` 态的语义 → 后续体验迭代（本批次 `stop_queue` 仅允许 `running`/`stopping`）。
- Prometheus 指标、多 worker 支持、`BEGIN IMMEDIATE` / 单写者架构 → 后续。

> 批次 2 完成后，队列状态机具备 `error`/`stopping_queue` 显式语义、并发写串行化、调度异常可见可恢复、孤儿任务统一回收，批次 3（性能）可在此稳固基座上安全重构 `serialize_queue` 的 N+1。
