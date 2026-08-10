# LlamaLens 任务队列设计

> 本文档基于对现有代码（`backend/app`、`frontend/src`）的扫描，在尽量复用现有 `BenchmarkJob` 执行链路的前提下，新增"任务 / 队列"两层抽象。本文为设计稿，确认无误后再进入实现。

## 1. 背景与目标

当前 `POST /api/v1/benchmarks` 创建 `BenchmarkJob` 后会**立即**提交到 `BENCHMARK_EXECUTOR`（单线程池）执行，没有"保存待执行"和"批量调度"的能力。

本次目标：

1. 创建 Benchmark 配置后**不立即执行**，而是保存为一个可复用的 **Task**（模式 A：Task 绑定 service + model_alias + 请求参数）。
2. 提供全局唯一**任务队列**，串行执行：一次只跑一个 Task。
3. 队列运行中允许动态：新增 Task、删除 Task、调整顺序；删除正在执行的 Task 时先优雅停止再移除。
4. 用户可配置 `intervalMs`（毫秒）：仅用于"上一个 Run 完成 → 下一个 Run 开始"之间，**第一个不等**。
5. Task 执行完成（成功/失败/取消）后从队列移除，但 Run 历史保留（复用 `benchmark_jobs` + `ResultsPage`）。
6. 队列跑空后**自动变 Idle**（模式 B），新增任务不会自动执行，需用户再次点击"开始队列"。
7. 失败策略：失败继续跑后续，但记录并提醒。

## 2. 现状分析（扫描结论）

| 现状 | 与本设计的关系 |
|---|---|
| `BenchmarkJob` 同时承载"配置 + 执行"（`config_json` + `status` + `attempts` + `summary`） | **直接复用为 Run**。一次执行 = 一个 `BenchmarkJob`。 |
| `BenchmarkAttempt` 记录每次请求指标 | 不动，仍由现有 `_run_job` 逻辑生成。 |
| `BENCHMARK_EXECUTOR`（`max_workers=1`）+ `EXECUTION_LOCK`（`threading.Lock`）保证串行 | 队列调度器作为**单一执行权威**，接管 Task 的执行；现有 `EXECUTION_LOCK` 继续用于串行化。 |
| 取消机制：`_cancelled_jobs: set[str]` + `_is_cancelled()` 在 wave/attempt 之间检查 | 复用为"优雅停止"信号；force 阶段额外处理（见 §9）。 |
| `_run_job_locked` 在 `EXECUTION_LOCK` 内跑完整个 job | 调度器线程直接调用等价逻辑，作为唯一 worker。 |
| `database.py` 用 `Base.metadata.create_all` + `_migrate_legacy_columns()` 增量迁移 | 新表用 `create_all` 建表；`benchmark_jobs` 增列走 `_migrate_legacy_columns` 同款 `ALTER TABLE`。 |
| 前端 `BenchmarkPage.vue` 表单 + 1s 轮询；`ResultsPage` 已有 Run 列表 | 表单改为"保存为 Task"；新增"任务/队列"页面；`ResultsPage` 增加按 Task 过滤。 |

**关键诚实结论**：现有 benchmark 执行器是 **HTTP 请求驱动**，没有可 `kill` 的子进程；取消是协作式（在 warmup 波次、repeat 轮次之间检查）。因此"强杀"在本设计中的真实语义是"停止等待 + 标记取消"，单个正在飞的 HTTP 请求只能等它返回或按 `timeout_seconds` 超时。详见 §9。

## 3. 概念与术语映射

| 术语 | 含义 | 落地对象 |
|---|---|---|
| Benchmark 配置 | 一次测量的请求参数（prompt、max_tokens、temperature、warmup、repeat、concurrency 等） | `BenchmarkCreate` payload |
| Task（任务） | 可复用、命名的执行意图，绑定 service + model_alias + Benchmark 配置 | 新表 `benchmark_tasks` |
| Run（执行记录） | Task 被执行一次产生的一条不可变记录 | 现有 `benchmark_jobs`（新增 `task_id` 列） |
| Queue（队列） | 全局单例串行调度器 | 新表 `task_queue`（单行）+ 调度线程 |
| QueueItem（队列项） | 某个 Task 在队列中的一次排队记录 | 新表 `task_queue_items` |

关系：`Benchmark 配置 → Task → QueueItem → Run(BenchmarkJob) → Attempt`。

## 4. 数据模型

### 4.1 新增表

#### `benchmark_tasks`（Task）
| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | VARCHAR(36) PK | uuid |
| `name` | VARCHAR(200) | 用户可读名称 |
| `service_id` | VARCHAR(36) INDEX | 绑定的 LlamaService（非 FK，service 可被归档；运行时校验） |
| `model_alias` | VARCHAR(200) | 绑定的模型 alias（必须在 applied 配置中存在，运行时校验） |
| `config_json` | TEXT | `BenchmarkCreate` 去除 name/service_id/model_alias 后的 payload（prompt、max_tokens、timeout_seconds、temperature、seed、stop、cache_prompt、warmup_runs、repeat_runs、repeat_delay_ms、concurrency、extra_params） |
| `last_run_status` | VARCHAR(32) NULL | 冗余，列表展示用 |
| `run_count` | INTEGER DEFAULT 0 | 冗余，列表展示用 |
| `created_at` / `updated_at` | DATETIME | |

#### `task_queue`（Queue 单例，固定 `id=1`）
| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK DEFAULT 1 | 单例 |
| `status` | VARCHAR(32) DEFAULT 'idle' | `idle` \| `running` \| `paused` \| `stopping` |
| `interval_ms` | INTEGER DEFAULT 0 | Run 完成后到下一个 Run 的等待毫秒；0 表示不等 |
| `cancel_timeout_ms` | INTEGER DEFAULT 60000 | 两段式停止的超时兜底 |
| `current_item_id` | VARCHAR(36) NULL | 当前执行的 QueueItem（指向 `task_queue_items.id`） |
| `next_dispatch_at` | DATETIME NULL | 下一次允许 dispatch 的时间戳（实现间隔 + 重启不丢倒计时） |
| `session_id` | VARCHAR(36) NULL | "本轮"标识，用于失败归档统计（开始队列时生成） |
| `updated_at` | DATETIME | |

#### `task_queue_items`（QueueItem，运行时队列项）
| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | VARCHAR(36) PK | uuid |
| `task_id` | VARCHAR(36) FK→`benchmark_tasks.id` ON DELETE CASCADE | 排队的 Task |
| `order_index` | INTEGER | 1 起，reorder 接口整体重写 |
| `status` | VARCHAR(32) DEFAULT 'waiting' | `waiting` \| `running`（`done`/`canceled` 为移除前的瞬态） |
| `enqueued_at` | DATETIME | |
| `started_at` | DATETIME NULL | |
| `last_run_id` | VARCHAR(36) NULL | 指向 `benchmark_jobs.id` |

约束（应用层保证）：表中**至多一条** `status='running'`，且等于 `task_queue.current_item_id`。

#### `task_queue_history`（Queue 操作审计，推荐）
| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK AUTO | |
| `item_id` | VARCHAR(36) NULL | item 删除后仍保留轨迹 |
| `task_id` | VARCHAR(36) | |
| `action` | VARCHAR(32) | `enqueued` \| `reordered` \| `started` \| `finished` \| `canceled` \| `removed` |
| `run_id` | VARCHAR(36) NULL | |
| `detail_json` | TEXT | 如 `{"from_index":..,"to_index":..}` |
| `at` | DATETIME | |

### 4.2 既有表扩展

`benchmark_jobs` 增列（走 `_migrate_legacy_columns` 同款 `ALTER TABLE`）：
- `task_id` VARCHAR(36) NULL INDEX —— 该 Run 属于哪个 Task（legacy quick-run 为 NULL）
- `queue_session_id` VARCHAR(36) NULL —— "本轮"归档（可选，便于失败统计）

### 4.3 迁移策略
- 新表：`Base.metadata.create_all` 创建。
- `benchmark_jobs` 增列：在 `_migrate_legacy_columns()` 内按现有模式追加 `ALTER TABLE ... ADD COLUMN` + `CREATE INDEX IF NOT EXISTS`。
- 不引入 Alembic（与现状一致）。

## 5. 状态机

### 5.1 Queue 状态
```
idle ──(用户点开始)──> running
running ──(队列耗尽)──> idle            # 模式 B
running ──(用户点暂停)──> paused
paused ──(用户点继续)──> running
running/paused ──(删除正在执行项)──> stopping ──(停止完成)──> running 或 idle
```
- `idle`：不调度；新增 Task 仅入队，不执行。
- `running`：调度器工作；当前可能有 Run 也可能正在等 `next_dispatch_at`。
- `paused`：不启动新 Run；不影响当前已启动的 Run（本设计不支持"暂停执行中"的 Run）。
- `stopping`：正在对 current item 做停止流程；期间禁用开始/暂停按钮。

### 5.2 QueueItem 状态
- `waiting`：排队中，可拖拽、可删除。
- `running`：正在执行（= `task_queue.current_item_id`）；不可拖拽，仅可"停止并删除"。
- `done` / `canceled`：瞬态，随即从表中删除（Run 历史已落入 `benchmark_jobs`）。

### 5.3 Run（BenchmarkJob）状态
沿用现有：`queued` → `running` → `succeeded` | `failed` | `cancelled`。
新增约定：重启时若发现 queue 关联的 Run 处于 `running`（进程已死），标记为 `failed`，`error="interrupted by restart"`。

## 6. 队列调度器（核心）

### 6.1 进程模型
新增一个**守护线程** `QueueScheduler`，在 FastAPI `lifespan` 启动时创建。它是**唯一的 benchmark 执行权威**：
- 队列触发的执行：调度线程内同步调用 `run_benchmark_job(job_id)`（等价于现有 `_run_job`：获取 `EXECUTION_LOCK` → 跑 warmup/repeat → 写 attempts/summary → 终态）。
- legacy `POST /benchmarks`（quick-run，不落 Task）：**保留**，但 `queue.status == 'running'` 或 `current_item_id` 非空时返回 `409`，避免与队列争抢 `EXECUTION_LOCK` 造成阻塞/死锁。

> 决策点 D1（见 §16）：是否保留 quick-run。本文建议保留但加 409 互斥。

### 6.2 调度循环
调度线程持有 `threading.Condition`，被以下事件 `notify`：开始队列、入队/重排/删除、取消当前、Run 完成（由调度线程自身感知，无需外部 notify）。

```
loop:
  with db:
    q = load_queue()
  if q.status not in (running, stopping): wait(); continue
  if q.current_item_id is None and q.status == running:
      # 可尝试 dispatch
      waiting = list_waiting_ordered()
      if not waiting:
          -> q.status = idle; q.next_dispatch_at = None; commit; continue
      if q.next_dispatch_at and now < q.next_dispatch_at:
          wait_until(q.next_dispatch_at); continue
      item = waiting[0]
      # 创建 Run（create_benchmark_job 的"仅创建不提交执行器"变体）
      try:
          job = create_run_for_task(item.task_id, session_id=q.session_id)
      except ValidationError as e:
          # service 已归档 / model_alias 失效 / applied 配置丢失
          mark_run_failed(item, error=str(e)); remove_item(item); 
          q.next_dispatch_at = now + interval_ms; continue
      item.status = running; item.started_at = now; item.last_run_id = job.id
      q.current_item_id = item.id; commit
      record_history(started, run_id=job.id)
  if q.current_item_id is not None:
      # 有正在执行的项：执行它（阻塞当前线程）
      run_benchmark_job(job.id)   # 内部持 EXECUTION_LOCK，跑完返回终态
      handle_run_finished(q, item, job)   # 见 6.4
```

### 6.3 dispatch 条件（严格定义）
同时满足才 dispatch：
1. `q.status == running`
2. `q.current_item_id is None`
3. 存在 `waiting` 项
4. `q.next_dispatch_at is None` **或** `now >= q.next_dispatch_at`

启动第一个任务时 `next_dispatch_at` 为 None → 立即执行（**首次不等**）。

### 6.4 Run 完成回调 `handle_run_finished`
1. 读 job 终态（succeeded/failed/cancelled）。
2. `record_history(finished|canceled, run_id=job.id, detail={status, error})`。
3. 删除该 QueueItem（`DELETE`）。
4. `q.current_item_id = None`。
5. 若 `q.status == stopping`（用户在执行期间点了停止并删除）：
   - `q.status = running` 如果还有 waiting（继续跑后续），否则 `idle`。
6. 否则（正常完成）：
   - 若还有 waiting：`q.next_dispatch_at = now + interval_ms`，下一轮循环到点再 dispatch。
   - 若无 waiting：`q.status = idle`，`q.next_dispatch_at = None`（模式 B）。
7. 失败提醒：若 job 终态为 `failed`，更新"本轮失败计数"（基于 `session_id`），前端轮询时展示。

## 7. 间隔与"首次不等"规则（intervalMs）
- 队列 `idle → running` 启动第一个 Task：`next_dispatch_at` 为 None → 立即 dispatch。
- 每个 Run `finished_at` 之后：`next_dispatch_at = finished_at + interval_ms`。
- `interval_ms = 0`：表示无间隔，下一个立刻可调度（仍受 dispatch 条件约束）。
- 持久化用时间戳而非"剩余秒数"，重启后倒计时可继续。

## 8. 运行中动态变更（增 / 删 / 排序）

### 8.1 新增 QueueItem
- `POST /queue/items {task_id, position?}`，默认追加队尾。
- 若 `q.status == running` 且当前空闲且到点：新增后可成为下一项（下一轮 dispatch 会被取出）。
- 若 `q.status == idle`：仅入队，不执行（模式 B）。

### 8.2 调整顺序
- `PATCH /queue/items/reorder {item_ids: [有序列表]}`：服务端重写 `order_index = 1..N`。
- 仅允许对 `status='waiting'` 项重排；`running` 项不参与（固定显示在顶部）。
- 重排立即生效，影响下一次 dispatch。

### 8.3 删除 Waiting 项
- `DELETE /queue/items/{id}`：直接删除 + `record_history(removed)`。

### 8.4 删除正在执行项（停止并删除，两段式）
`DELETE /queue/items/{id}` 且该 item 是 `current_item_id`：
1. `q.status = stopping`，commit。
2. 设置取消信号：`_cancelled_jobs.add(job.id)`（复用现有机制）。
3. 调度线程在下一个 wave/attempt 间隙检测到取消 → `_run_job` 提前退出 → job 置 `cancelled`。
4. `handle_run_finished` 走 §6.4 第 5 步分支：删除 item，恢复 `running`/`idle`。
5. **超时兜底（force）**：若 `cancel_timeout_ms` 内 job 未进入终态（卡在长 HTTP 请求），调度线程强制：
   - job.status = `cancelled`，`error` 追加 `"; force-stopped after timeout"`，`termination_mode='force'`（存入 config 或 summary 的扩展字段）。
   - 继续走删除 item + 恢复队列。
   - 后台仍在飞的 HTTP 响应到达后被丢弃（受 `timeout_seconds` 上界约束）。

> 诚实说明：现有执行器无法中断单个 `httpx.stream` 请求。force 阶段是"放弃等待 + 标记 + 继续"，不是"杀死 HTTP"。§16 的 D2 列出了可选增强。

## 9. 失败策略与提醒
- 任意 Run 终态为 `failed`：队列**继续**（按 `interval_ms` 调度下一个）。
- 记录：`benchmark_jobs.error` + `task_queue_history(action=finished, detail={status:failed})`。
- 提醒：
  - Queue 页面顶部展示"本轮执行：成功 X / 失败 Y / 取消 Z"（基于 `session_id` 聚合 `benchmark_jobs.queue_session_id`）。
  - 失败计数 > 0 时高亮（红点 / banner），点击可过滤到失败 Run。
  - Task 列表的 `last_run_status` 同步变红。
- "本轮"边界：用户点击"开始队列"生成新 `session_id`；队列回到 `idle` 时本轮结束（计数定格）。

## 10. 持久化与重启恢复
所有对象持久化（SQLite WAL）。服务重启 / 页面刷新后：
1. 加载 `task_queue` 单例。
2. 若 `current_item_id` 非空：其对应 Run 状态必为 `running`（进程已死）→ 标记该 Run 为 `failed`（`error="interrupted by restart"`），删除该 QueueItem，`record_history(canceled, detail={reason:restart})`，`current_item_id = None`。
3. `q.status` 一律置为 `idle`（重启后不自动恢复 running，符合模式 B 的安全语义）。
4. `next_dispatch_at` 若指向未来：保留（下次 start 后仍生效）；若已过期：清空。
5. Waiting 队列原样保留，顺序不变。
6. 用户重新点击"开始队列"即可继续。

## 11. API 契约

> 路由前缀 `/api/v1`，写操作复用现有认证策略。状态推送 V1 维持 1s 轮询。

### Tasks
```
GET    /tasks                       列表（含 last_run_status, run_count）
POST   /tasks                       创建 {name, service_id, model_alias, ...benchmarkParams}
                                    校验：service 未归档 + 有 applied + model_alias ∈ applied aliases，否则 409
GET    /tasks/{id}                  详情 + 最近若干 Run
PATCH  /tasks/{id}                  编辑
DELETE /tasks/{id}                  删除；若其有 running 队列项 → 先停止并移除（或拒绝，见 D3）
GET    /tasks/{id}/runs             该 Task 的 Run 列表
```

### Queue（单例）
```
GET    /queue                       状态 + items(有序) + current run 概要 + 本轮统计
PATCH  /queue                       {status?: "start"|"pause", interval_ms?, cancel_timeout_ms?}
POST   /queue/items                 {task_id, position?: "tail"|"head"|<index>}
PATCH  /queue/items/reorder         {item_ids: [有序]}
DELETE /queue/items/{id}            删除；running 项触发两段式停止
GET    /queue/history               队列操作审计（可选）
```

### Runs（复用现有，扩展过滤）
```
GET    /benchmarks?task_id=...      按 Task 过滤 Run（原 /benchmarks 列表扩展 query）
GET    /benchmarks/{id}             详情（含 attempts，不变）
GET    /benchmarks/{id}/attempts/{aid}  不变
POST   /benchmarks/{id}/cancel     legacy/直接取消单个 Run（不删队列项）
POST   /benchmarks                  legacy quick-run；queue 运行中返回 409
DELETE /benchmarks/{id}            不变（仅终态可删）
```

### 序列化要点
- `GET /queue` 返回：`{status, interval_ms, cancel_timeout_ms, current_item:{task, run:{id,status,summary...}}, items:[{id, task_id, task_name, order_index, status, enqueued_at, last_run_id}], session:{id, successes, failures, canceled}}`。
- Task 序列化新增 `last_run_status`、`run_count`、`bound_service_name`、`bound_model_alias`。

## 12. 前端信息架构

### 12.1 导航调整
将原 `Benchmark` 入口语义化为"任务"体系，建议导航：
```
概览 | Services | 模型库 | Profiles | 任务 | 结果 | 设置
```
- `/tasks`：任务中心，含两个 Tab：
  - **任务库**：所有 Task 列表（名称、绑定 service/model_alias、last_run_status、run_count）。操作：新建任务、加入队列、查看历史、编辑、删除。
  - **队列**：全局任务队列（核心交互页）。
- `/benchmark`：保留为"新建/编辑任务"的表单页（从"任务库"的"新建任务"按钮进入），主按钮由"开始测试"改为"保存为任务"，次按钮"保存并加入队列"。

### 12.2 队列页（/tasks → 队列 Tab）
- 顶部控制条：
  - Queue 状态徽标（Idle / Running / Paused / Stopping）
  - `interval_ms` 输入（毫秒，min 0）
  - `cancel_timeout_ms` 输入（高级，可折叠）
  - 开始 / 暂停 按钮（Stopping 时禁用）
  - 本轮统计：成功 X / 失败 Y / 取消 Z（失败高亮）
- 当前运行区（Running）：
  - Task 名、Run id、状态、summary 指标（TTFT/Prefill/Decode 摘要，复用 `MetricBlock`）
  - "停止并删除"按钮（触发两段式停止，二次确认）
  - 链接到 `/results` 对应 Run 详情
- 等待队列区（Waiting）：
  - 拖拽排序（仅 waiting 项可拖）
  - 每项：Task 名、绑定 service/model_alias、入队时间
  - 删除按钮
  - 空态提示："队列为空。开始队列后，首个任务将立即执行（不等待间隔）。"
- 历史区（折叠）：本轮 Run 列表，失败项高亮，点击跳转 `/results`。

### 12.3 任务库页（/tasks → 任务库 Tab）
- 列表：名称、绑定 service · model_alias、last_run_status、run_count、updated_at。
- 行操作：加入队列、立即（加入并置顶）、查看 Run 历史、编辑、删除。
- "新建任务" → `/benchmark` 表单。

### 12.4 结果页（/results）
- 增加按 Task 过滤（`task_id` query）。
- Run 详情不变；展示所属 Task 名（便于追溯）。

### 12.5 轮询
- 队列页 1s 轮询 `GET /queue`（沿用现有 1s polling 模式，后续可无破坏升级为 WebSocket）。
- 队列 `idle` 或无 current run 时降低到 2-3s（小优化）。

## 13. 与现有代码的集成点 / 改动清单

### 后端
| 文件 | 改动 |
|---|---|
| `app/models.py` | 新增 `BenchmarkTask`、`TaskQueue`、`TaskQueueItem`、`TaskQueueHistory` 模型；`BenchmarkJob` 增 `task_id`、`queue_session_id` 列。 |
| `app/schemas.py` | 新增 `TaskCreate/TaskUpdate/TaskOut`、`QueuePatch`、`QueueItemCreate`、`ReorderInput`；`BenchmarkCreate` 不变。 |
| `app/services/benchmark.py` | 抽出 `create_benchmark_job` 的"仅创建 Run 记录 + 构造 config snapshot"部分为 `create_run_for_task(task_id, session_id)`；保留 `_run_job`/`_run_job_locked` 逻辑供调度线程调用；`cancel_benchmark` 复用。 |
| 新增 `app/services/task_queue.py` | `QueueScheduler` 守护线程 + 调度循环 + dispatch/finish/cancel/force 逻辑；启动/停止/入队/重排/删除 的服务函数。 |
| 新增 `app/api/tasks.py`、`app/api/queue.py` | REST 路由。 |
| `app/database.py` | `_migrate_legacy_columns` 增加 `benchmark_jobs.task_id/queue_session_id`；新表由 `create_all` 处理。 |
| `app/main.py` | `lifespan` 启动 `QueueScheduler` 线程；注册新路由；注册重启恢复逻辑。 |
| `app/api/benchmarks.py` | `POST /benchmarks` 增加"queue 运行中 409"互斥；`list_jobs` 支持 `task_id` 过滤。 |

### 前端
| 文件 | 改动 |
|---|---|
| `src/types.ts` | 新增 `Task`、`TaskQueue`、`QueueItem`、`QueueSession` 接口。 |
| `src/api.ts` | 新增 tasks/queue 相关调用封装（沿用 `api<T>`）。 |
| `src/views/TasksPage.vue`（新增） | 任务库 + 队列 双 Tab 页面。 |
| `src/views/BenchmarkPage.vue` | 主按钮改为"保存为任务"；保留表单字段；可选"保存并加入队列"。 |
| `src/views/ResultsPage.vue` | 增加 `task_id` 过滤；展示 Task 名。 |
| `src/router.ts` | 新增 `/tasks`；`/benchmark` 语义改为任务编辑器。 |
| `src/App.vue` | 导航项：`Benchmark` → `任务`。 |
| `src/stores/app.ts` | 可选：队列轮询状态片段。 |

## 14. 边界、风险与已知限制

| 风险 / 限制 | 处理 |
|---|---|
| 执行器无法硬杀单个 HTTP 请求 | 两段式停止：优雅取消（wave 间隙）→ 超时强制标记；in-flight 请求受 `timeout_seconds` 上界。force 阶段语义为"放弃等待 + 标记 + 继续"，非"杀 HTTP"。 |
| 重启时 Run 卡在 running | 启动恢复统一标记 failed("interrupted by restart")，队列置 idle。 |
| quick-run 与队列争锁 | queue 运行中 `POST /benchmarks` 返回 409。 |
| Task 引用的 service 被归档 | dispatch 时 `create_run_for_task` 校验失败 → Run 直接 failed，队列继续（失败策略）。 |
| `order_index` 并发重排 | reorder 接口整体重写（事务内 `1..N`），避免浮点精度与竞争。 |
| 长时间 Stopping 卡死 | `cancel_timeout_ms` 兜底；超时强制进入终态。 |
| 前端轮询压力 | 队列空闲时降频；后续可升级 WebSocket。 |
| 历史膨胀 | `benchmark_jobs`/`attempts` 沿用现有保留策略；`task_queue_history` 建议加保留期（后续）。 |

## 15. 实施阶段与验收

| 阶段 | 交付 | 验收 |
|---|---|---|
| 0. 数据层 | 新增 4 表 + `benchmark_jobs` 增列 + 迁移 | 重启不报错；旧库自动增列；`GET /tasks`、`GET /queue` 可空返回。 |
| 1. Task CRUD | `/tasks` 全套接口 + `/benchmark` 保存为任务 | 创建 Task 校验 service/model_alias；可编辑/删除；列表含 last_run_status。 |
| 2. 队列调度 | `QueueScheduler` + `/queue` + items CRUD + reorder | 加入多个 Task → 开始 → 串行执行；intervalMs 在 Run 之间生效、首个不等；耗尽转 idle。 |
| 3. 动态变更 + 停止 | 运行中增/删/排序；删除 running 项两段式停止 | 运行中拖拽 waiting 生效；删除 running 触发取消→终态→恢复 running/idle；超时 force 生效。 |
| 4. 失败与恢复 | 失败继续 + 本轮统计 + 重启恢复 | 制造失败 Run，队列继续且 UI 高亮；重启后卡死 Run 标记 failed，队列 idle。 |
| 5. 前端 | 任务库 + 队列页 + Results 过滤 + 导航 | 端到端：新建任务→入队→开始→实时查看→停止→历史回看。 |

## 16. 待确认决策点

| 编号 | 决策 | 建议（默认） |
|---|---|---|
| D1 | 是否保留 `POST /benchmarks` quick-run（不落 Task 立即跑） | 保留，但 queue 运行中返回 409。 |
| D2 | 是否在 force 阶段真正中断 in-flight HTTP（需重构 `_stream_measurement` 为可 cancel 的 `httpx` + 关闭 stream） | V1 不做，仅"放弃等待 + 标记"；列为后续增强。 |
| D3 | 删除 Task 时若其有 running 队列项：先停止并移除，还是拒绝删除？ | 先停止并移除（与"删除正在执行项"一致），二次确认。 |
| D4 | 队列页与任务库是否合并为单页双 Tab | 是（`/tasks` 双 Tab，导航更精简）。 |
| D5 | `task_queue_history` 审计表是否首期实现 | 建议实现（成本极低，便于排查"顺序怎么变的"）。 |
| D6 | 队列跑空转 idle 后，是否保留"自动运行"开关（未来优化） | V1 不做，严格遵守模式 B。 |

---

确认本文档无误后，将按 §15 阶段推进实现：先数据层 + Task CRUD，再队列调度器，最后前端。
