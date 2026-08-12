# LlamaLens 优化设计方案（v2）

> 本文档基于 2026-08-07 对 LlamaLens 全栈项目的复查，相较 v1 已纳入新增的**任务队列系统**、**观测页（Observation）**、**图表组件拆分**、**Excel 导出**等变更。
> 标注 ✅ 已解决 / ⚠️ 部分解决 / 🔴 未解决，并补充新发现的问题。所有事项仍处于**设计阶段**，尚未实现。

---

## 一、项目现状概览（相较 v1 的变化）

| 层 | 技术栈 | v1 → v2 变化 |
|---|---|---|
| 后端 | FastAPI + SQLAlchemy 2.0 + SQLite | 新增持久化任务队列（`TaskQueue` / `TaskQueueItem` / `TaskQueueHistory` / `BenchmarkTask`），`QueueScheduler` 守护线程，启动回收 |
| 前端 | Vue 3 + TS + Vite + Pinia + ECharts | 新增观测页、Excel 导出（`excelExporter.ts`）、图表拆为 `components/charts/*`、`utils.ts` / `metricsStats.ts` 工具 |
| 测试 | pytest（仅后端） | 仍无前端测试、无 lint、无 CI |

**已新增能力：** 任务库 + 串行执行队列 + 拖拽排序 + 会话统计 + 历史记录；观测页多图对比 + Excel 导出（含图表截图嵌入）。

---

## 二、安全与正确性

### 1. 缺少认证/鉴权 —— 🔴 未解决
应用以 root 运行，可写 systemd unit、调用 systemctl、发起下载、读取 journal。`backend/app/main.py` 仍无 auth 中间件。

**设计方案：**
- 引入 `APIKeyHeader` + `secrets.compare_digest`，settings 存 `api_token_hash`（仅哈希）。
- 新增 `Depends(verify_token)` 或 `AuthMiddleware`，`LLAMALENS_REQUIRE_AUTH=1` 控制 loopback 免认证。

### 2. 孤儿任务回收 —— ⚠️ 部分解决
任务队列的 `task_queue.recover_on_startup()` 已能在重启时回收**队列内**的 `running`/`queued` job，并标记为 `failed`。但：
- 队列**之外**直接创建的 Benchmark（`create_benchmark_job` 走 `BENCHMARK_EXECUTOR`）重启后仍会卡在 `running`。
- 下载任务 `DownloadJob`（`models_service.EXECUTOR`）重启后仍卡死，且 `_cancelled_downloads` 是内存集合会丢失。

**设计方案：**
- 在 `lifespan` 中统一扫描所有 `status in ('running','queued')` 的 `BenchmarkJob` 与 `DownloadJob`（不限于队列内），标记 `failed` 并写 `error="interrupted by restart"`。
- 或令 `recover_on_startup` 同时覆盖 standalone benchmark 与 download 两类。

### 3. `list_arguments` 每次请求重建种子目录 —— 🔴 未解决
`backend/app/api/arguments.py` 的 `list_arguments`（L24）、`refresh`（L53）、`categories`（L59）仍都调用 `seed_builtin_catalog(db)`，而 `lifespan` 已播种一次。

**设计方案：** 移除 `list_arguments` / `categories` 的 `seed_builtin_catalog` 调用，仅保留启动播种 + `/arguments/refresh` 显式刷新。

### 4.（新增）队列调度线程静默吞异常 —— 🔴 新发现
`task_queue.py` 的 `_loop` 中：
```python
except Exception:
    pass
```
若 `_tick()` 因 DB 锁、代码 bug 反复失败，会无限空转且无任何日志（全项目无 logging），故障不可见。

**设计方案：** 引入 `logging.exception`，并对连续失败计数，超阈值时将队列置为 `error` 态并在 API 响应中暴露。

---

## 三、性能（N+1 与重复计算）

### 5. `list_jobs` 为每个 job 加载全部 attempts 重算均值 —— 🔴 未解决
`backend/app/api/benchmarks.py` 的 `_serialize`（L22-33）仍对每个 job 遍历 `job.attempts` 重算 `average`，而 `summary_json` 里已存有结果。列表 200 个 job 触发 200 次懒加载。

**设计方案：**
- 列表接口直接用 `summary_json` 中已有 metrics，不再遍历 `job.attempts`。
- 给 `_serialize` 增加 `lightweight=True` 参数，仅详情接口 `include_attempts=True` 时加载 attempts。

### 6.（新增）`serialize_queue` 的 N+1 —— 🔴 新发现
`task_queue.py` 的 `serialize_queue` 对每个 `TaskQueueItem` 调用 `_serialize_item`，内部各做一次 `db.get(BenchmarkTask)` + 可选 `db.get(BenchmarkJob)`；`session_stats` 还按 session 全表扫 `BenchmarkJob`。该接口被 `TasksPage` **每 1 秒轮询**一次，N 个队列项 = 每秒 ~2N 次查询。

**设计方案：**
- 一次性 `select(BenchmarkTask).where(id.in_(...))` 批量加载 task；`last_run_id` 批量加载 job。
- `session_stats` 改为 `group by status` 聚合查询，而非 Python 端循环。

### 7. `list_profiles` 每个 profile 触发两次全表扫描 —— 🔴 未解决
`profiles_service.serialize_profile` → `build_launch_argv` → `known_flags(db)` + `canonical_flags(db)`，N 个 profile = 2N 次扫描。

**设计方案：** 在 `list_profiles` 中一次性加载 `known_flags` / `canonical_flags`，传入复用；或加进程内缓存（参数目录改动频率极低）。

### 8. `list_services?with_status=true` 串行调用 systemctl —— 🔴 未解决
N 个服务串行 N 次子进程。

**设计方案：** `ThreadPoolExecutor` 并行，或一次性 `systemctl list-units 'llamalens-*' --output=json` 批量获取后 join。

### 9. 下载进度逐 chunk commit —— 🔴 未解决
`models_service._run_download` 每 1MB chunk 都 `db.commit()`，大文件产生数千次磁盘写。

**设计方案：** 按时间/字节节流提交（每 2s 或 16MB），结束再 commit 终态。

### 10.（新增）TasksPage 队列 1s 轮询无退避 —— 🟡 新发现
队列状态每 1s 轮询 `/queue`，即使队列 `idle` 且无任务也持续轮询，浪费请求。

**设计方案：** `idle` 且无 `current_item` 时切换到 5s 慢轮询；或后端用 SSE 推送队列变更（scheduler 已有 condition，可顺势推送）。

---

## 四、架构与可维护性

### 11. 手写迁移逻辑脆弱 —— 🔴 未解决
`database._migrate_legacy_columns` 是长串 `ALTER TABLE` + 多次 `inspect(engine)`，无版本记录。

**设计方案：** 引入 Alembic，baseline 抽取当前 schema，后续走 migration 脚本。

### 12. 大文件拆分与职责分离 —— 🔴 未解决
- `benchmark.py`（~590 行）混合 job 创建、执行编排、HTTP 测量、SSE 解析、资源采样、序列化。
- `arguments.py` 的 `BUILTIN_ARGUMENTS`（113 项）内联硬编码。
- 新增的 `task_queue.py`（~440 行）也混合了 ORM 操作、调度循环、序列化、历史记录。

**设计方案：**
- 拆 `benchmark.py` → `benchmark_runner.py` / `measurement.py` / `resource_sampler.py` / `benchmark_serializer.py`。
- 拆 `task_queue.py` → `queue_repository.py`（ORM）/ `queue_scheduler.py`（调度循环）/ `queue_serializer.py`。
- `BUILTIN_ARGUMENTS` 外置为 `app/data/builtin_arguments.json`。

### 13. 缺少结构化日志 —— 🔴 未解决（且因新调度线程更迫切）
全项目无 `logging`，新调度线程还静默吞异常。

**设计方案：** 配置 `structlog` 或标准 `logging`，统一 JSON 日志：systemctl 调用 argv/returncode、benchmark 生命周期、队列调度事件、下载事件、未捕获异常栈。

### 14.（新增）队列并发写入无显式锁 —— 🟡 新发现
`QueueScheduler` 用独立 `SessionLocal`，API 请求用请求级 session，二者可并发写 `TaskQueue` / `TaskQueueItem`。SQLite 默认隔离下，并发 commit 可能 `database is locked`。`enqueue_item` 的 `head` 分支逐条 `order_index += 1` 期间，scheduler 可能正在 dispatch。

**设计方案：**
- 引入进程内 `threading.Lock` 串行化队列状态变更（enqueue / reorder / delete / dispatch）。
- 或 SQLite `BEGIN IMMEDIATE` 显式加写锁。
- 长期看，调度逻辑与状态变更应通过单一 ownership（如让 scheduler 线程作为唯一写者，API 仅投递事件）。

### 15.（新增）`stopping` 语义可能反直觉 —— 🟡 新发现
`delete_item` 删除当前运行项时置 `stopping`，运行结束后若仍有 `waiting` 项，`_handle_run_finished` 会把状态**回到 `running`** 继续执行后续任务。

**设计方案：** 明确语义——是"仅停止当前任务"还是"停止整个队列"。若为前者，UI 文案应改为"停止当前任务"；若用户期望停止整队，应提供独立的"停止队列"操作将状态置 `idle`。当前 `TasksPage` 只有"暂停"无"停止"，建议补充。

### 16.（新增）Excel 导出阻塞主线程 —— 🟢 新发现
`excelExporter.exportObservationExcel` 虽为 `async`，但内部 `workbook.xlsx.writeBuffer()` 是重 CPU 同步操作，会阻塞 UI 渲染。

**设计方案：** 用 Web Worker 执行 ExcelJS 序列化；或至少在导出前 `await nextTick` 显示 loading，分块 `await` 让出主线程。

---

## 五、前端优化

### 17. 缺少 API 客户端抽象层 —— 🔴 未解决
视图仍直接 `api<T>('/queue/items/reorder', ...)` 内联拼字符串。新增的 TasksPage、ObservationPage 同样如此，路径与类型手动同步。

**设计方案：** 新建 `src/api/tasks.ts` / `queue.ts` / `observation.ts` 等，端点封装为强类型函数。

### 18. 深拷贝用 `JSON.parse(JSON.stringify())` —— 🔴 未解决
**改进点：** 新增 `src/utils.ts` 已提供 `formatDate` 等工具，但深拷贝仍散落各处。

**设计方案：** 在 `utils.ts` 增加 `cloneConfig`（`structuredClone`），统一替换。

### 19. 部分操作无 busy 态 —— 🔴 未解决
新增 `TasksPage` 的 `deleteItem` / `reorder` 未设 busy，拖拽过程中可重复触发。

**设计方案：** 抽 `useAsync` 组合式函数管理 loading/error，或逐操作加 `busy` ref。

### 20. 无前端测试、无 ESLint —— 🔴 未解决
新增 `excelExporter.ts`（复杂导出逻辑）、`metricsStats.ts`（统计聚合）、`chartAxis.ts`（轴布局）均无测试覆盖。

**设计方案：**
- Vitest + `@vue/test-utils`，优先覆盖 `metricsStats`（纯函数易测）、`excelExporter`（mock ExcelJS）、`chartAxis`。
- ESLint flat config + Prettier，配 `npm run lint`；后端 `pyproject.toml` 加 `ruff`。

### 21. i18n 缺失 —— 🔴 未解决
所有文案硬编码中文（含 TasksPage、ObservationPage 新增文案）。

**设计方案：** 引入 `vue-i18n`，抽取 locale 文件。

### 22. BenchmarkPage 轮询无实时推送 —— 🔴 未解决
**新契机：** 队列 scheduler 已有 `threading.Condition`，可顺势实现 SSE 推送队列与任务状态，替代 TasksPage / BenchmarkPage 轮询。

**设计方案：** FastAPI `StreamingResponse` + `EventSourceResponse`，scheduler 在状态变更时通知 SSE 通道；前端 `EventSource` 订阅。

---

## 六、部署与可观测性

### 23. 无容器化、无 CI/CD —— 🔴 未解决
**设计方案：** 多阶段 Dockerfile（前端 build + 后端 slim）；GitHub Actions 跑 `pytest` + `npm run build` + lint；`docker-compose.yml` 带卷挂载。

### 24. 健康检查与可观测性薄弱 —— 🔴 未解决
`/api/v1/health` 只返回 `{"status":"ok"}`。

**设计方案：** `/health` 增加 DB ping；新增 `/ready`；可选 Prometheus metrics（队列深度、systemctl 调用次数、请求耗时）。

### 25. 列表接口无分页 —— 🔴 未解决
`list_jobs`（limit 200）、`list_profiles`、`list_models`、新增的 `list_tasks` 均无分页。

**设计方案：** 统一 `?offset&limit` + 总数返回，ResultsPage / TasksPage 加分页或无限滚动。

---

## 七、优化实施优先级建议（更新版）

| 优先级 | 事项 | 状态 | 收益 | 复杂度 |
|---|---|---|---|---|
| P0 | #2 统一孤儿任务回收（standalone benchmark + download） | ⚠️ 部分解决 | 正确性 | 低 |
| P0 | #3 移除冗余 seed_builtin_catalog | 🔴 未解决 | API 延迟 | 低 |
| P0 | #5 list_jobs 不重算均值 | 🔴 未解决 | 列表性能数十倍 | 低 |
| P0 | #6 serialize_queue 批量加载 + 聚合统计 | 🔴 新发现 | 队列轮询性能 | 中 |
| P0 | #4 调度线程异常日志 + 失败保护 | 🔴 新发现 | 可见性/稳定性 | 低 |
| P1 | #1 认证中间件 | 🔴 未解决 | 安全 | 中 |
| P1 | #7 list_profiles 复用 flags | 🔴 未解决 | 列表性能 | 低 |
| P1 | #8 systemctl 并行/批量 | 🔴 未解决 | 服务列表响应 | 中 |
| P1 | #13 结构化日志 | 🔴 未解决 | 可运维 | 中 |
| P1 | #14 队列并发写锁 | 🟡 新发现 | 稳定性 | 中 |
| P1 | #20 前端测试 + ESLint | 🔴 未解决 | 质量基线 | 中 |
| P2 | #9 下载 chunk 节流 commit | 🔴 未解决 | IO | 低 |
| P2 | #10 队列 idle 慢轮询 / SSE | 🟡 新发现 | 请求量 | 中 |
| P2 | #11 Alembic 迁移 | 🔴 未解决 | 长期维护 | 中高 |
| P2 | #12 拆分 benchmark.py / task_queue.py | 🔴 未解决 | 可维护 | 中 |
| P2 | #17 前端 API 抽象层 | 🔴 未解决 | 可维护 | 中 |
| P2 | #23 Dockerfile + CI | 🔴 未解决 | 部署标准化 | 中 |
| P3 | #15 stopping 语义明确化 | 🟡 新发现 | 体验/正确性 | 低 |
| P3 | #16 Excel 导出移至 Web Worker | 🟢 新发现 | UI 流畅 | 中 |
| P3 | #22 SSE 推送替代轮询 | 🔴 未解决 | 体验/请求量 | 高 |
| P3 | #21 i18n、#24 监控、#25 分页 | 🔴 未解决 | 体验/可观测 | 中 |

---

## 八、实施路径建议（更新版）

1. **第一阶段（P0 快速收益）：** #2 统一回收、#3 移除冗余 seed、#5 list_jobs 轻量化、#6 队列序列化批量化、#4 调度异常日志。低复杂度、高收益，一轮迭代可交付。
2. **第二阶段（安全与稳定性基线）：** #1 认证中间件、#14 队列写锁、#13 结构化日志。
3. **第三阶段（性能与前端质量）：** #7、#8、#10、#20 前端测试 + ESLint。
4. **第四阶段（架构演进）：** #11 Alembic、#12 拆分大文件、#17 前端 API 层、#23 容器化 + CI。
5. **第五阶段（体验增强）：** #15 语义、#16 Web Worker、#22 SSE、#21 i18n、#24 监控、#25 分页。

每个阶段完成后回归验证：`pytest backend/tests` + `npm run build`（当前无 lint，建议第二阶段引入后追加 `npm run lint` + `ruff check`）。

---

## 九、v1 → v2 进展小结

| v1 编号 | v1 事项 | 当前状态 |
|---|---|---|
| #1 | 认证中间件 | 🔴 未解决 |
| #2 | 孤儿任务回收 | ⚠️ 队列内已回收，standalone benchmark / download 未回收 |
| #3 | 移除冗余 seed_builtin_catalog | 🔴 未解决 |
| #4 | list_jobs 不重算均值 | 🔴 未解决 |
| #5 | list_profiles 复用 flags | 🔴 未解决 |
| #6 | systemctl 并行 | 🔴 未解决 |
| #7 | 下载 chunk 节流 | 🔴 未解决 |
| #8 | Alembic 迁移 | 🔴 未解决 |
| #9 | 拆分 benchmark.py | 🔴 未解决 |
| #10 | 结构化日志 | 🔴 未解决 |
| #11 | EXECUTION_LOCK 注释 | 🔴 未解决 |
| #12 | 前端 API 抽象层 | 🔴 未解决 |
| #13 | 深拷贝工具 | 🔴 未解决 |
| #14 | SSE 推送替代轮询 | 🔴 未解决 |
| #15 | 操作 busy 态 | 🔴 未解决 |
| #16 | 前端测试 + ESLint | 🔴 未解决 |
| #17 | i18n | 🔴 未解决 |
| #18 | Dockerfile + CI | 🔴 未解决 |
| #19 | 健康检查 | 🔴 未解决 |
| #20 | 列表分页 | 🔴 未解决 |

> **结论：** v1 列出的 20 项优化均尚未实施，但项目在功能维度（任务队列、观测页、Excel 导出）有显著推进。功能扩张同时引入了 6 项新问题（#4 调度吞异常、#6 队列 N+1、#10 队列轮询、#14 并发写锁、#15 stopping 语义、#16 Excel 阻塞），建议优先消化 P0 项以避免技术债随功能继续累积。

---

## 十、问题分类与批量解决建议

将 25 项归为 **5 个批次**。同批次内的问题"同类 / 同文件 / 共享基础设施"，可一起解决，减少反复改同一处代码。

### 批次 1：后端基础设施（日志 + 认证 + 健康检查）
> 合并原 D + G。日志是基础设施，认证需要日志记录事件，健康检查也属可观测性。被批次 2、3 依赖，应最先做。

| # | 事项 | 文件 | 说明 |
|---|---|---|---|
| 13 | 结构化日志 | 全项目 | 无 `logging`，调度线程吞异常 |
| 1 | 认证中间件 | `main.py` | 无任何 auth（应用以 root 运行） |
| 24 | 健康检查与监控 | `main.py` / `api/system.py` | `/health` 无 DB ping |

**一起做的理由：** 引入 `structlog` 后，认证失败/命中事件可直接打日志；`/health` 的 DB ping、可选 Prometheus metrics 一并加上。这三者构成"安全 + 可观测"底座。

### 批次 2：队列系统加固（孤儿回收 + 调度异常 + 并发锁 + stopping 语义）
> 合并原 B + C。都集中在 `task_queue.py` 和后台线程层，是同一状态机与生命周期问题，连续改一处即可。

| # | 事项 | 文件 | 说明 |
|---|---|---|---|
| 2 | 统一孤儿任务回收 | `main.py` lifespan / `task_queue.py` | 队列内已回收，standalone benchmark + download 未回收 |
| 4 | 调度线程静默吞异常 | `task_queue.py` `_loop` | `except Exception: pass` 无日志 |
| 14 | 队列并发写入无显式锁 | `task_queue.py` | SQLite 可能 `database is locked` |
| 15 | `stopping` 语义反直觉 | `task_queue.py` `_handle_run_finished` | 停止当前项后自动恢复 running |

**一起做的理由：** #2 改 `recover_on_startup` 覆盖全部 job 类型时，#4 顺手给调度线程加异常日志（依赖批次 1 日志已就位）；#14 引入 `threading.Lock` 串行化状态变更时，正好明确 #15 的 `stopping` 语义（补"停止整队"操作）。四者都在队列状态机这一层，一次性改透。

### 批次 3：后端性能优化（N+1 序列化 + 列表分页 + 子进程并行 + IO 节流）
> 合并原 A + E。都是"把同步/串行/懒加载的查询与外部操作改为批量/并行/节流"，模式统一。

| # | 事项 | 文件 | 说明 |
|---|---|---|---|
| 5 | list_jobs 不重算均值 | `api/benchmarks.py` | 遍历 `job.attempts` 重算已有均值 |
| 6 | serialize_queue 的 N+1 | `task_queue.py` | 每项 `db.get` 两次 + session 全表扫 |
| 7 | list_profiles 两次全表扫描 | `profiles_service.py` | 每 profile 触发 `known_flags` + `canonical_flags` |
| 25 | 列表分页 | 4 个 list 接口 | 顺带加 `?offset&limit` + 总数 |
| 8 | systemctl 并行/批量 | `llama_services.py` | N 个服务串行 N 次子进程 |
| 9 | 下载 chunk 节流 commit | `models_service.py` | 每 1MB commit 一次 |

**一起做的理由：** #5/#6/#7/#25 都是 `*_serialize` 函数内的 N+1，改法相同（list 层批量预加载 + 复用）；#8/#9 都是同步串行外部操作改并行/节流，可共用 `ThreadPoolExecutor` 封装。一次性建立"轻量化序列化 + 节流"规范，后续新接口沿用。

### 批次 4：前端工程化与体验（API 层 + 工具 + 测试 + 体验项）
> 合并原 F + I。API 抽象层是其他前端改动的前置地基，测试覆盖新建代码，体验项在此基础上推进。

| # | 事项 | 文件 | 说明 |
|---|---|---|---|
| 17 | 前端 API 抽象层 | `src/api.ts` + 新建 `src/api/*` | 视图内联拼字符串 |
| 18 | 深拷贝工具 | `src/utils.ts` | `JSON.parse(JSON.stringify())` |
| 20 | 前端测试 + ESLint | 新建 vitest/eslint | 无测试无 lint |
| 19 | 操作 busy 态 | 各 Page.vue | 无防重复提交 |
| 10 | 队列 idle 慢轮询 | `TasksPage.vue` | 轮询无退避 |
| 16 | Excel 导出 Web Worker | `excelExporter.ts` | writeBuffer 阻塞主线程 |
| 22 | SSE 推送替代轮询 | 后端 + `BenchmarkPage`/`TasksPage` | 依赖 scheduler Condition |
| 21 | i18n | 全前端 | 文案硬编码 |

**一起做的理由：** #17 API 层 + #18 工具是"地基"；#20 测试正好覆盖新建的 API 层、工具函数（`metricsStats` / `chartAxis`）；#19/#10/#16 是前端交互稳定性与流畅度，基于前述地基推进。**建议顺序：** #17 → #18 → #20 → #19 → #10 → #16 → #22 → #21。

**依赖：** #22（SSE）与批次 2 的队列 scheduler 关联，但可独立设计；#25 前端分页依赖批次 3 后端分页，可放此批次末尾或合并到批次 3。

### 批次 5：架构重构与部署（Alembic + 拆分大文件 + 数据外置 + 容器化 CI）
> 合并原 H。都是"大动作重构"，彼此关联度高但风险大，独立迭代。

| # | 事项 | 文件 | 说明 |
|---|---|---|---|
| 3 | 移除冗余 seed_builtin_catalog | `api/arguments.py` | 顺带做 |
| 12 | 拆分大文件 | `benchmark.py` / `task_queue.py` / arguments 数据 | 单文件数百行 |
| 11 | Alembic 迁移 | `database.py` → 新建 migrations | 手写迁移无版本 |
| 23 | Dockerfile + CI | 新建 | 无容器化 |

**一起做的理由：** #12 数据外置（`BUILTIN_ARGUMENTS` → JSON）与 #11 Alembic 都涉及目录结构重组；#3 顺带清掉冗余 seed；#23 CI 正好需要 Alembic + lint + test 都就位后才能跑全套检查。**建议顺序：** #3（顺手）→ #12 数据外置 + 拆分 → #11 Alembic → #23 容器化 + CI。

---

## 十一、依赖关系与推荐批次顺序

```
批次 1（日志/认证/健康）─┬─> 批次 2（队列加固，依赖日志）
                        └─> 批次 3 的调度异常排查也依赖日志

批次 3（性能：N+1 + 分页 + 子进程/IO）─> 批次 4 的 #25 前端分页

批次 4（前端工程化与体验）  独立，可与 1-3 并行
批次 5（架构重构 + 部署）   独立，最后做
```

**推荐落地顺序（考虑收益/依赖/风险）：**

1. **批次 1**：结构化日志 + 认证 + 健康检查（安全与可观测底座，被批次 2/3 依赖）
2. **批次 2**：队列系统加固——孤儿回收 + 调度异常 + 并发锁 + stopping 语义（依赖批次 1 日志）
3. **批次 3**：后端性能——N+1 序列化 + 分页 + systemctl 并行 + 下载节流（收益最大）
4. **批次 4**：前端工程化与体验——API 层 + 工具 + 测试 + busy/轮询/Web Worker/SSE/i18n（可与 1-3 并行）
5. **批次 5**：架构重构与部署——Alembic + 拆分大文件 + 数据外置 + 容器化 CI

> **关键洞察：** 批次 1、2、3 都涉及"序列化 / 状态机 / 日志"——这是后端最容易出 bug 的区域，建议连续迭代完成，避免改一半留隐患。批次 4（前端）可与 1-3 并行推进，互不阻塞。
