# LlamaLens 优化设计方案（v2）

> 本文档基于 2026-08-07 对 LlamaLens 全栈项目的复查，相较 v1 已纳入新增的**任务队列系统**、**观测页（Observation）**、**图表组件拆分**、**Excel 导出**等变更。
> 标注 ✅ 已解决 / ⚠️ 部分解决 / 🔴 未解决，并补充新发现的问题。
>
> **进展更新（2026-08-11）：** 批次 1（结构化日志 #13 + 认证中间件 #1 + 健康检查 #24）已实现并通过验证（`pytest` 48 passed + `npm run build` 通过），详见各问题条目与第十节批次表。实现过程中发现并修复了 `QueueScheduler.start()` 的预存隐患（线程重启报错，见文末"批次 1 实施记录"）。
>
> **进展更新（2026-08-12）：** 批次 2（孤儿回收 #2 + 调度异常 #4 + 并发写锁 #14 + stopping 语义 #15）已实现并通过验证（`pytest` 58 passed + `npm run build` 通过），详见各问题条目、第十节批次表与文末"批次 2 实施记录"。实现中将队列状态机扩展为含 `error`/`stopping_queue` 态、引入进程内 `threading.Lock`、`/ready` 增加 `queue_status` + `scheduler_failures` 探测。
>
> **进展更新（2026-08-12）：** 批次 3（轻量化序列化 #5 + 队列 N+1 #6 + flags 复用 #7 + systemctl 批量 #8 + 下载节流 #9 + 列表分页 #25）已实现并通过验证（`pytest` 67 passed + `npm run build` 通过），详见各问题条目、第十节批次表与文末"批次 3 实施记录"。统一建立"轻量化序列化 + 批量预加载 + 节流提交"规范：列表接口用 `summary_json` 已有 metrics 跳过 attempts 遍历、`id.in_()` 批量加载 + `GROUP BY` 聚合、`systemctl list-units --output=json` 一次拿全部单元状态、下载双维度（2s/16MB）commit 节流、5 个列表接口统一 `?offset&limit` + `{items,total,offset,limit}` 包裹返回（前端 7 个消费页面同步适配）。
>
> **进展更新（2026-08-13）：** 批次 4（API 抽象 #17 + 深拷贝 #18 + busy 防重 #19 + 前端测试/lint #20 + 慢轮询 #10 + Excel Worker #16 + SSE #22 + i18n #21）已实现并通过验证：前端 **54 tests passed**、后端 **70 tests passed**、ESLint **0 error**、`npm run build` 通过。实现中修复了 API 入口同名自引用导致的全量类型构建失败，以及 SSE 空闲时未捕获 `queue.Empty`、连接约 5 秒后异常断开的真实缺陷。设计详见 `docs/batch4-design.md`，实施记录见文末“批次 4 实施记录”。

---

## 一、项目现状概览（相较 v1 的变化）

| 层 | 技术栈 | v1 → v2 变化 |
|---|---|---|
| 后端 | FastAPI + SQLAlchemy 2.0 + SQLite | 新增持久化任务队列（`TaskQueue` / `TaskQueueItem` / `TaskQueueHistory` / `BenchmarkTask`），`QueueScheduler` 守护线程，启动回收 |
| 前端 | Vue 3 + TS + Vite + Pinia + ECharts + vue-i18n | API 按模块分层、队列 SSE、Excel Web Worker、中英双语、统一 busy 防重；观测图表拆为 `components/charts/*` |
| 测试 | pytest + Vitest + Vue Test Utils + ESLint | 后端 70 tests、前端 54 tests；已有 lint 基线，仍无 CI |

**已新增能力：** 任务库 + 串行执行队列 + 拖拽排序 + 会话统计 + 历史记录；观测页多图对比 + Excel 导出（含图表截图嵌入）。

---

## 二、安全与正确性

### 1. 缺少认证/鉴权 —— ✅ 已解决（批次 1，2026-08-11）
应用以 root 运行，可写 systemd unit、调用 systemctl、发起下载、读取 journal。`backend/app/main.py` 仍无 auth 中间件。

**设计方案（已实现）：**
- 新增独立表 `AuthSecret(id=1, token_hash, updated_at)`（**不**放入 `AppSettings`，避免 `GET /settings` 回显哈希）。
- 令牌哈希用 `hashlib.sha256`，比对用 `secrets.compare_digest`（时序安全）。
- 启动引导：`LLAMALENS_API_TOKEN` env 非空时写入 DB 哈希（仅存哈希）；env 为空则沿用 DB 哈希；二者皆无则鉴权关闭（向后兼容）。
- `verify_auth` FastAPI 依赖挂载到全部业务 router；loopback（`127.0.0.1`/`::1`/`localhost`，基于 `request.client.host`，不信 `X-Forwarded-For`）默认免认证，`LLAMALENS_REQUIRE_AUTH=1` 强制。
- 免鉴权路径：`/health` `/ready` `/auth/status` `/auth/login`；`/auth/rotate` 需鉴权。
- 前端：登录页 + `localStorage`，`api.ts` 自动附加 `Authorization: Bearer`，401 清令牌并跳登录。

### 2. 孤儿任务回收 —— ✅ 已解决（批次 2，2026-08-12）
任务队列的 `task_queue.recover_on_startup()` 原先仅回收**队列内**的 `running`/`queued` job。队列之外的 standalone Benchmark 与 `DownloadJob` 重启后仍卡死。

**设计方案（已实现）：**
- `recover_on_startup()` 拆为三步：`_recover_queue_current_item`（队列当前项）/ `_recover_standalone_benchmarks`（全表扫 `BenchmarkJob` 的 `running`/`queued`）/ `_recover_downloads`（全表扫 `DownloadJob`，并清理 `.part` 临时文件）。
- 三类 job 统一标记 `failed`、写 `error="interrupted by restart"`、补 `finished_at`；队列当前项删除、`current_item_id=None`、`status="idle"`。
- `.part` 清理用 `Path(target).with_suffix(suffix + ".part").unlink(missing_ok=True)`，失败仅 warning 不中断回收。

### 3. `list_arguments` 每次请求重建种子目录 —— 🔴 未解决
`backend/app/api/arguments.py` 的 `list_arguments`（L24）、`refresh`（L53）、`categories`（L59）仍都调用 `seed_builtin_catalog(db)`，而 `lifespan` 已播种一次。

**设计方案：** 移除 `list_arguments` / `categories` 的 `seed_builtin_catalog` 调用，仅保留启动播种 + `/arguments/refresh` 显式刷新。

### 4.（新增）队列调度线程静默吞异常 —— ✅ 已解决（批次 2，2026-08-12）
`task_queue.py` 的 `_loop` 中原为 `except Exception: pass`，`_tick()` 反复失败会无限空转且无日志。

**设计方案（已实现）：**
- 删除 `except: pass`，改为 `except Exception as exc: self._handle_tick_failure(exc)`，内部 `logger.exception("queue.tick_failed")` 并递增 `_consecutive_failures`。
- 连续失败达阈值（`LLAMALENS_QUEUE_FAILURE_THRESHOLD`，默认 5）后 `_persist_error_state()` 将 `TaskQueue.status` 置为 `error`（复用 `status` 字符串列，不加表/列/迁移）。
- `error` 态每轮循环开始 `_attempt_error_recovery()` 乐观恢复到 `_pre_error_status`；一次 `_tick` 成功即 `_on_tick_success()` 清零计数。
- `QueueScheduler.diagnostics()` 暴露 `consecutive_failures` / `last_error` / `last_error_at` / `failure_threshold`，`serialize_queue` 附带、`/ready` 据此判 `degraded`。
- `POST /queue/reset` 提供手动复位（仅 `error` 态允许，非 `error` 返回 409）。

---

## 三、性能（N+1 与重复计算）

### 5. `list_jobs` 为每个 job 加载全部 attempts 重算均值 —— ✅ 已解决（批次 3，2026-08-12）
`backend/app/api/benchmarks.py` 的 `_serialize`（L22-33）仍对每个 job 遍历 `job.attempts` 重算 `average`，而 `summary_json` 里已存有结果。列表 200 个 job 触发 200 次懒加载。

**设计方案（已实现）：**
- 列表接口直接用 `summary_json` 中已有 metrics，不再遍历 `job.attempts`。
- 给 `_serialize` 增加 `lightweight=True` 参数，仅详情接口 `include_attempts=True` 时加载 attempts。`list_jobs` 默认 `lightweight=True`。

### 6.（新增）`serialize_queue` 的 N+1 —— ✅ 已解决（批次 3，2026-08-12）
`task_queue.py` 的 `serialize_queue` 对每个 `TaskQueueItem` 调用 `_serialize_item`，内部各做一次 `db.get(BenchmarkTask)` + 可选 `db.get(BenchmarkJob)`；`session_stats` 还按 session 全表扫 `BenchmarkJob`。该接口被 `TasksPage` **每 1 秒轮询**一次，N 个队列项 = 每秒 ~2N 次查询。

**设计方案（已实现）：**
- 一次性 `select(BenchmarkTask).where(id.in_(...))` 批量加载 task；`last_run_id` 批量加载 job。`_serialize_item` 签名改为接收预加载的 task/job，不再内部 `db.get`。
- `session_stats` 改为 `SELECT status, COUNT(*) ... GROUP BY status` 聚合查询，而非 Python 端循环。查询数从 ~2N 降为常数（3 条）。

### 7. `list_profiles` 每个 profile 触发两次全表扫描 —— ✅ 已解决（批次 3，2026-08-12）
`profiles_service.serialize_profile` → `build_launch_argv` → `known_flags(db)` + `canonical_flags(db)`，N 个 profile = 2N 次扫描。

**设计方案（已实现）：**
- 在 `list_profiles` 入口一次性加载 `known_flags` / `canonical_flags`，传入各 profile 复用（2N → 2）。采用"每请求查一次"而非进程内缓存，避免缓存失效与一致性复杂度。

### 8. `list_services?with_status=true` 串行调用 systemctl —— ✅ 已解决（批次 3，2026-08-12）
N 个服务串行 N 次子进程。

**设计方案（已实现）：** 新增 `systemd.list_units_status(pattern, timeout)` 执行 `systemctl list-units 'llamalens-*' --output=json --all --no-pager` 一次拿全部单元状态，按 unit 名建字典；`list_services` 在 `with_status=True` 时调用一次，`serialize_service` 接收 `unit_status` 字典按名 join（不再逐个调子进程）。N 次子进程降为 1 次。

### 9. 下载进度逐 chunk commit —— ✅ 已解决（批次 3，2026-08-12）
`models_service._run_download` 每 1MB chunk 都 `db.commit()`，大文件产生数千次磁盘写。

**设计方案（已实现）：** 双维度节流——满足"距上次 commit ≥ 2s"或"累计写入 ≥ 16MB"任一才 `db.commit()`；结束再 commit 终态。取消检查每 chunk 执行不节流（保证及时中断）。阈值可配置（`LLAMALENS_DOWNLOAD_COMMIT_INTERVAL_MS` 默认 2000、`LLAMALENS_DOWNLOAD_COMMIT_INTERVAL_BYTES` 默认 16MB）。

### 10.（新增）TasksPage 队列 1s 轮询无退避 —— ✅ 已解决（批次 4，2026-08-13）
队列状态每 1s 轮询 `/queue`，即使队列 `idle` 且无任务也持续轮询，浪费请求。

**设计方案（已实现）：** 正常状态使用 SSE 推送；SSE 断线时自动降级为自适应轮询，`running` / `stopping` / `stopping_queue` 为 1s，`idle` 等静态状态为 5s。重连间隔与轮询间隔集中在 `frontend/src/config.ts`，前端销毁时统一关闭 EventSource、轮询与重连定时器。

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

### 13. 缺少结构化日志 —— ✅ 已解决（批次 1，2026-08-11）
全项目无 `logging`，新调度线程还静默吞异常。

**设计方案（已实现）：**
- 标准库 `logging` + 自定义 `JsonFormatter`（零新依赖），输出 `ts/level/logger/event/msg + extra 平铺 + exc_info` 到 stdout（由 journal/容器日志接管）。
- `app/logging_config.py` 提供 `LOGGING_CONFIG` / `setup_logging()` / `get_logger()`；`web.py` 传 `log_config` 给 uvicorn 统一应用与 access 日志格式；`main.py` lifespan 调 `setup_logging()`。
- 事件接入：`lifespan.starting/stopped`、`systemctl.*`（argv/returncode/stderr 截断）、`benchmark.created/started/finished/failed/cancel_requested`、`download.start/finished/cancelled/failed`（URL 仅记 netloc）、`queue.item_started/item_finished`、`auth.failed/loopback_exempt/token_bootstrapped/token_rotated`、全局 `uncaught_exception`。
- 级别由 `LLAMALENS_LOG_LEVEL`（默认 INFO）控制；令牌明文绝不进日志。
- **注：** #4 调度线程 `except: pass` 已在批次 2（2026-08-12）解决（连续失败计数 + `error` 态 + `/queue/reset`）。

### 14.（新增）队列并发写入无显式锁 —— ✅ 已解决（批次 2，2026-08-12）
`QueueScheduler` 用独立 `SessionLocal`，API 请求用请求级 session，二者可并发写 `TaskQueue` / `TaskQueueItem`，并发 commit 可能 `database is locked`；`enqueue_item` 的 `head` 分支逐条 `order_index += 1` 期间 scheduler 可能正在 dispatch。

**设计方案（已实现）：**
- 模块级 `_queue_lock = threading.Lock()` 串行化全部队列状态变更临界区：`start_queue` / `pause_queue` / `update_queue_settings` / `enqueue_item` / `reorder_items` / `delete_item` / `stop_queue` / `reset_queue` / `_tick` 内的 `_try_dispatch` / `_handle_run_finished`。
- `run_benchmark_job(job_id)` 长任务**锁外**执行，避免持锁过久；与 `benchmark.EXECUTION_LOCK` 层级不同、互不嵌套，无死锁风险。
- 跨会话防御：`database._configure_sqlite` PRAGMA 追加 `busy_timeout=5000`，与进程内锁形成两道防线。
- `recover_on_startup` 的三步回收也各自在 `_queue_lock` 下与 `_try_dispatch` 串行。

### 15.（新增）`stopping` 语义可能反直觉 —— ✅ 已解决（批次 2，2026-08-12）
`delete_item` 删除当前运行项时置 `stopping`，运行结束后 `_handle_run_finished` 会把状态**回到 `running`** 继续执行后续任务，与用户"停止"的直觉不符。

**设计方案（已实现）：**
- 明确区分两种停止语义：
  - **停止当前任务**（`delete_item` 当前项）：置 `stopping`，run 结束后删除当前项、若有 `waiting` 项则 `status` 回 `running` 继续、否则 `idle`。前端按钮文案改为"停止当前任务"并加 `title` 说明。
  - **停止队列**（新增 `stop_queue` / `PATCH status=stop`）：置 `stopping_queue`、`cancel_benchmark` 当前 job，run 结束后当前项回 `waiting`（`last_run_id=None`、`started_at=None`）、`q.status="idle"`、整队停止。仅 `running`/`stopping` 态允许触发，避免与 `paused` 冲突。
- 前端 `TasksPage.vue` 新增"停止队列"（danger）/"复位队列"（warning）按钮与 `error` 横幅；`types.ts` 的 `status` 扩展 `'stopping_queue' | 'error'` 并附带 `scheduler` 诊断字段。

### 16.（新增）Excel 导出阻塞主线程 —— ✅ 已解决（批次 4，2026-08-13）
`excelExporter.exportObservationExcel` 虽为 `async`，但内部 `workbook.xlsx.writeBuffer()` 是重 CPU 同步操作，会阻塞 UI 渲染。

**设计方案（已实现）：** 拆出 `buildWorkbookBlob()` / `downloadBlob()`，新增 `workers/excelExport.worker.ts` 在 Worker 内执行 ExcelJS 序列化；`ObservationPage` 用 `postMessage` 传递结构化数据，收到 Blob 后在主线程触发下载。构建产物包含独立 `excelExport.worker-*.js` chunk。

---

## 五、前端优化

### 17. 缺少 API 客户端抽象层 —— ✅ 已解决（批次 4，2026-08-13）
视图仍直接 `api<T>('/queue/items/reorder', ...)` 内联拼字符串。新增的 TasksPage、ObservationPage 同样如此，路径与类型手动同步。

**设计方案（已实现）：** 新建 `src/api/`，按 `auth` / `benchmarks` / `profiles` / `models` / `tasks` / `queue` / `services` / `settings` / `arguments` 拆分强类型 API；`client.ts` 集中处理 base URL、query、JSON body、认证、401 跳转与 AbortSignal。扫描确认 API 层外直接 `fetch/request/api` 调用为 0。兼容入口 `src/api.ts` 显式 re-export `./api/index`。

### 18. 深拷贝用 `JSON.parse(JSON.stringify())` —— ✅ 已解决（批次 4，2026-08-13）
**改进点：** 新增 `src/utils.ts` 已提供 `formatDate` 等工具，但深拷贝仍散落各处。

**设计方案（已实现）：** `utils.ts` 增加 `cloneConfig`，优先使用 `structuredClone`；仅在老浏览器不支持时保留 JSON fallback。Profiles/Services 的配置复制全部改用该工具，并覆盖嵌套对象、数组与 Date 测试。

### 19. 部分操作无 busy 态 —— ✅ 已解决（批次 4，2026-08-13）
新增 `TasksPage` 的 `deleteItem` / `reorder` 未设 busy，拖拽过程中可重复触发。

**设计方案（已实现）：** 新增 `useBusy()`，按操作 key 管理独立 busy 状态并拒绝重复执行；Tasks、Profiles、Services、Benchmark、Observation 的写操作均接入，按钮同步绑定 disabled。队列 start/pause/stop/reset、入队、删除、重排，Service deploy/action/archive/restore/delete 等操作互不覆盖状态。

### 20. 无前端测试、无 ESLint —— ✅ 已解决（批次 4，2026-08-13）
新增 `excelExporter.ts`（复杂导出逻辑）、`metricsStats.ts`（统计聚合）、`chartAxis.ts`（轴布局）均无测试覆盖。

**设计方案（已实现）：**
- 引入 Vitest、`@vue/test-utils`、jsdom，覆盖 `metricsStats`、`excelExporter`、`chartAxis`、`utils`、`StatusBadge`，共 5 个测试文件、54 个用例。
- 引入 ESLint flat config、typescript-eslint、eslint-plugin-vue，提供 `test` / `test:watch` / `lint` / `lint:fix` 脚本。当前 lint 为 0 error、13 warnings；warning 主要来自 `LaunchConfigEditor` 作为受控表单编辑嵌套 prop，以及测试 mock 中 1 处 `any`。
- 本批次未引入 Prettier 和后端 Ruff；留给 CI/代码规范专项处理。

### 21. i18n 缺失 —— ✅ 已解决（批次 4，2026-08-13）
所有文案硬编码中文（含 TasksPage、ObservationPage 新增文案）。

**设计方案（已实现）：** 引入 `vue-i18n`，新增 `zh.json` / `en.json`，设置页支持即时切换并持久化 locale。页面、共享 LaunchConfigEditor 与观测图表文案已提取；源码中保留的“中文”仅为语言选择器中的语言名称。

### 22. BenchmarkPage 轮询无实时推送 —— ✅ 已解决（批次 4，2026-08-13）
**新契机：** 队列 scheduler 已有 `threading.Condition`，可顺势实现 SSE 推送队列与任务状态，替代 TasksPage / BenchmarkPage 轮询。

**设计方案（已实现）：** 后端新增 `/api/v1/events/queue` StreamingResponse、query token 认证与 QueueScheduler 订阅/发布总线；TasksPage 用 `useQueueStream()` 接收队列快照。当前 BenchmarkPage 只负责保存/入队后跳转 TasksPage，已不存在旧版本 active-job 轮询，因此无需维持第二条 SSE 连接。SSE 专项测试覆盖初始事件、publish、keepalive 与 unsubscribe。

---

## 六、部署与可观测性

### 23. 无容器化、无 CI/CD —— 🔴 未解决
**设计方案：** 多阶段 Dockerfile（前端 build + 后端 slim）；GitHub Actions 跑 `pytest` + `npm run build` + lint；`docker-compose.yml` 带卷挂载。

### 24. 健康检查与可观测性薄弱 —— ✅ 已解决（部分，批次 1，2026-08-11）
`/api/v1/health` 只返回 `{"status":"ok"}`。

**设计方案（已实现）：**
- `/health` 升级为 `{"status":"ok","db":"ok"}`，DB ping 用 `SELECT 1`。
- 新增 `/ready`：`{"status":"ready","checks":{"db":"ok","scheduler_alive":true}}`，`ready`/`degraded` 据实判断；`scheduler_alive` 取 `QueueScheduler.is_alive()`（本批次新增）。
- `/health` `/ready` 免鉴权，供 systemd/容器探针直连。
- **未做（延后）：** Prometheus 指标（队列深度、systemctl 调用计数、请求耗时直方图）——后续专门迭代。

### 25. 列表接口无分页 —— ✅ 已解决（批次 3，2026-08-12）
`list_jobs`（limit 200）、`list_profiles`、`list_models`、新增的 `list_tasks` 均无分页。

**设计方案（已实现）：** 统一 `?offset&limit`（默认 offset=0/limit=50，limit 上限 200）+ `func.count()` total + `{items, total, offset, limit}` 包裹对象返回。5 个列表接口（`/benchmarks`、`/profiles`、`/models`、`/models/downloads`、`/tasks`）全部改造；前端 7 个消费页面（ResultsPage 加载更多、ProfilesPage/ModelsPage/TasksPage/DashboardPage/ServicesPage/ObservationPage）同步适配解构 `.items`。`list_profiles` 因此移除 `response_model=list[ProfileOut]`（返回类型已变）。

---

## 七、优化实施优先级建议（更新版）

| 优先级 | 事项 | 状态 | 收益 | 复杂度 |
|---|---|---|---|---|
| P0 | #2 统一孤儿任务回收（standalone benchmark + download） | ✅ 已解决（批次2） | 正确性 | 低 |
| P0 | #3 移除冗余 seed_builtin_catalog | 🔴 未解决 | API 延迟 | 低 |
| P0 | #5 list_jobs 不重算均值 | ✅ 已解决（批次3） | 列表性能数十倍 | 低 |
| P0 | #6 serialize_queue 批量加载 + 聚合统计 | ✅ 已解决（批次3） | 队列轮询性能 | 中 |
| P0 | #4 调度线程异常日志 + 失败保护 | ✅ 已解决（批次2） | 可见性/稳定性 | 低 |
| P1 | #1 认证中间件 | ✅ 已解决（批次1） | 安全 | 中 |
| P1 | #7 list_profiles 复用 flags | ✅ 已解决（批次3） | 列表性能 | 低 |
| P1 | #8 systemctl 并行/批量 | ✅ 已解决（批次3） | 服务列表响应 | 中 |
| P1 | #13 结构化日志 | ✅ 已解决（批次1） | 可运维 | 中 |
| P1 | #14 队列并发写锁 | ✅ 已解决（批次2） | 稳定性 | 中 |
| P1 | #20 前端测试 + ESLint | ✅ 已解决（批次4） | 质量基线 | 中 |
| P2 | #9 下载 chunk 节流 commit | ✅ 已解决（批次3） | IO | 低 |
| P2 | #10 队列 idle 慢轮询 / SSE | ✅ 已解决（批次4） | 请求量 | 中 |
| P2 | #11 Alembic 迁移 | 🔴 未解决 | 长期维护 | 中高 |
| P2 | #12 拆分 benchmark.py / task_queue.py | 🔴 未解决 | 可维护 | 中 |
| P2 | #17 前端 API 抽象层 | ✅ 已解决（批次4） | 可维护 | 中 |
| P2 | #23 Dockerfile + CI | 🔴 未解决 | 部署标准化 | 中 |
| P3 | #15 stopping 语义明确化 | ✅ 已解决（批次2） | 体验/正确性 | 低 |
| P3 | #16 Excel 导出移至 Web Worker | ✅ 已解决（批次4） | UI 流畅 | 中 |
| P3 | #22 SSE 推送替代轮询 | ✅ 已解决（批次4） | 体验/请求量 | 高 |
| P3 | #21 i18n、#25 分页 | ✅ #21 批次4、#25 批次3 | 体验/可观测 | 中 |
| — | #24 健康检查 | ✅ 已解决（批次1，Prometheus 延后） | 可观测 | 中 |

---

## 八、实施路径建议（更新版）

1. **第一阶段（P0 快速收益）：** #2 统一回收 ✅、#3 移除冗余 seed、#5 list_jobs 轻量化 ✅、#6 队列序列化批量化 ✅、#4 调度异常日志 ✅。低复杂度、高收益，一轮迭代可交付。
2. **第二阶段（安全与稳定性基线）：** #1 认证中间件 ✅、#14 队列写锁 ✅、#13 结构化日志 ✅、#15 stopping 语义 ✅（其中 #1/#13 在批次 1，#14/#15 在批次 2）。
3. **第三阶段（性能与前端质量）：** #7 ✅、#8 ✅、#9 ✅、#25 ✅（批次 3）；#10、#17、#18、#19、#20 ✅（批次 4）。
4. **第四阶段（架构演进）：** #11 Alembic、#12 拆分大文件、#23 容器化 + CI；#17 API 层已由批次 4 提前完成。
5. **第五阶段（体验增强）：** #16 Web Worker、#22 SSE、#21 i18n ✅（批次 4）；#24 Prometheus 监控仍待后续专项。

每个阶段完成后回归验证：`pytest backend/tests` + `npm run test` + `npm run lint` + `npm run build`。后端 Ruff 尚未引入，待批次 5 CI/规范专项补充。

---

## 九、v1 → v2 进展小结

| v1 编号 | v1 事项 | 当前状态 |
|---|---|---|
| #1 | 认证中间件 | ✅ 已解决（批次1） |
| #2 | 孤儿任务回收 | ✅ 已解决（批次2，standalone benchmark + download 全覆盖） |
| #3 | 移除冗余 seed_builtin_catalog | 🔴 未解决 |
| #4 | list_jobs 不重算均值 | ✅ 已解决（批次3，对应 v2 #5） |
| #5 | list_profiles 复用 flags | ✅ 已解决（批次3，对应 v2 #7） |
| #6 | systemctl 并行 | ✅ 已解决（批次3，对应 v2 #8） |
| #7 | 下载 chunk 节流 | ✅ 已解决（批次3，对应 v2 #9） |
| #8 | Alembic 迁移 | 🔴 未解决 |
| #9 | 拆分 benchmark.py | 🔴 未解决 |
| #10 | 结构化日志 | ✅ 已解决（批次1，对应 v2 #13） |
| #11 | EXECUTION_LOCK 注释 | 🔴 未解决 |
| #12 | 前端 API 抽象层 | ✅ 已解决（批次4，对应 v2 #17） |
| #13 | 深拷贝工具 | ✅ 已解决（批次4，对应 v2 #18） |
| #14 | SSE 推送替代轮询 | ✅ 已解决（批次4，对应 v2 #22） |
| #15 | 操作 busy 态 | ✅ 已解决（批次4，对应 v2 #19） |
| #16 | 前端测试 + ESLint | ✅ 已解决（批次4，对应 v2 #20） |
| #17 | i18n | ✅ 已解决（批次4，对应 v2 #21） |
| #18 | Dockerfile + CI | 🔴 未解决 |
| #19 | 健康检查 | ✅ 已解决（批次1，对应 v2 #24，Prometheus 延后） |
| #20 | 列表分页 | ✅ 已解决（批次3，对应 v2 #25） |

> **结论（截至 2026-08-13）：** v1 列出的 20 项中已解决 15 项。批次 4 新解决 #12 API 抽象、#13 深拷贝、#14 SSE、#15 busy、#16 前端测试/lint、#17 i18n；同时解决 v2 新增的 #10 队列慢轮询和 #16 Excel 主线程阻塞。仍未解决的是 v1 #3 冗余播种、#8 Alembic、#9 大文件拆分、#11 EXECUTION_LOCK 注释、#18 Dockerfile/CI，集中归入批次 5。

---

## 十、问题分类与批量解决建议

将 25 项归为 **5 个批次**。同批次内的问题"同类 / 同文件 / 共享基础设施"，可一起解决，减少反复改同一处代码。

### 批次 1：后端基础设施（日志 + 认证 + 健康检查）—— ✅ 已完成（2026-08-11）
> 合并原 D + G。日志是基础设施，认证需要日志记录事件，健康检查也属可观测性。被批次 2、3 依赖，应最先做。

| # | 事项 | 文件 | 说明 | 状态 |
|---|---|---|---|---|
| 13 | 结构化日志 | 全项目 | 无 `logging`，调度线程吞异常 | ✅ 标准库 logging + JsonFormatter，事件接入 systemctl/benchmark/download/queue/lifespan/uncaught |
| 1 | 认证中间件 | `main.py` | 无任何 auth（应用以 root 运行） | ✅ AuthSecret 表 + env 引导 + verify_auth 依赖 + 登录页 |
| 24 | 健康检查与监控 | `main.py` / `api/system.py` | `/health` 无 DB ping | ✅ /health 加 DB ping + /ready（Prometheus 延后） |

**完成情况：** `pytest backend/tests` 48 passed（含新增 17 个 auth/health/logging 用例）；`npm run build` 通过。设计详见 `docs/batch1-design.md`。实现中发现并修复 `QueueScheduler.start()` 预存隐患（见文末实施记录）。这三者构成"安全 + 可观测"底座，批次 2 可直接用 `logger.exception` 改造调度异常、用 `/ready` 扩展失败计数。

### 批次 2：队列系统加固（孤儿回收 + 调度异常 + 并发锁 + stopping 语义）—— ✅ 已完成（2026-08-12）
> 合并原 B + C。都集中在 `task_queue.py` 和后台线程层，是同一状态机与生命周期问题，连续改一处即可。

| # | 事项 | 文件 | 说明 | 状态 |
|---|---|---|---|---|
| 2 | 统一孤儿任务回收 | `task_queue.py` `recover_on_startup` | 三步回收：队列当前项 + standalone benchmark + download（含 `.part` 清理） | ✅ |
| 4 | 调度线程静默吞异常 | `task_queue.py` `_loop` / `QueueScheduler` | 删 `except: pass`，连续失败计数 + `error` 态 + `diagnostics()` + `/queue/reset` | ✅ |
| 14 | 队列并发写入无显式锁 | `task_queue.py` / `database.py` | 模块级 `_queue_lock` 串行化全部临界区（长任务锁外）+ `busy_timeout=5000` | ✅ |
| 15 | `stopping` 语义反直觉 | `task_queue.py` `_handle_run_finished` / `api/queue.py` / `TasksPage.vue` | 区分"停止当前任务"（`stopping`）与"停止队列"（`stopping_queue`） | ✅ |

**一起做的理由：** #2 改 `recover_on_startup` 覆盖全部 job 类型时，#4 顺手给调度线程加异常日志（依赖批次 1 日志已就位）；#14 引入 `threading.Lock` 串行化状态变更时，正好明确 #15 的 `stopping` 语义（补"停止整队"操作）。四者都在队列状态机这一层，一次性改透。

**完成情况：** `pytest backend/tests` **58 passed**（含新增 10 个 `test_task_queue.py` 用例：孤儿回收 / 错误态阈值 / 自动恢复 / `/ready` degraded / 诊断暴露 / 手动复位 + 409 / 停止队列回队首 / 停止并删除 / 8 线程并发 enqueue）；`npm run build`（含 vue-tsc）通过。设计详见 `docs/batch2-design.md`。实现中自检发现并修正两处隐藏问题（`error` 态下 `_tick` 提前 return 致 `_on_tick_success` 永不调用 → 新增 `_attempt_error_recovery`；`_handle_run_finished` 中途异常会重跑已 finished job → `_tick` 增加 job-terminal 守卫）。未引入新表/列/迁移（`error`/`stopping_queue` 复用 `status` 字符串列 + 内存计数），#11 Alembic 留待批次 5。

### 批次 3：后端性能优化（N+1 序列化 + 列表分页 + 子进程并行 + IO 节流）—— ✅ 已完成（2026-08-12）
> 合并原 A + E。都是"把同步/串行/懒加载的查询与外部操作改为批量/并行/节流"，模式统一。

| # | 事项 | 文件 | 说明 | 状态 |
|---|---|---|---|---|
| 5 | list_jobs 不重算均值 | `api/benchmarks.py` | 遍历 `job.attempts` 重算已有均值 | ✅ `_serialize(lightweight=True)` + 列表用 `summary_json` |
| 6 | serialize_queue 的 N+1 | `task_queue.py` | 每项 `db.get` 两次 + session 全表扫 | ✅ `id.in_()` 批量预加载 + `GROUP BY` 聚合 |
| 7 | list_profiles 两次全表扫描 | `profiles_service.py` / `api/profiles.py` | 每 profile 触发 `known_flags` + `canonical_flags` | ✅ 入口一次性加载 flags 传入复用（2N→2） |
| 25 | 列表分页 | 5 个 list 接口 + 7 个前端页面 | `?offset&limit` + `{items,total,offset,limit}` 包裹 | ✅ 5 接口 + 前端 7 页面同步适配 |
| 8 | systemctl 并行/批量 | `services/systemd.py` / `llama_services.py` / `api/services.py` | N 个服务串行 N 次子进程 | ✅ `list_units_status` 一次拿全 + `unit_status` 字典 join |
| 9 | 下载 chunk 节流 commit | `services/models_service.py` | 每 1MB commit 一次 | ✅ 双维度节流（2s/16MB）+ 可配置阈值 |

**一起做的理由：** #5/#6/#7/#25 都是 `*_serialize` 函数内的 N+1，改法相同（list 层批量预加载 + 复用）；#8/#9 都是同步串行外部操作改并行/节流，可共用 `ThreadPoolExecutor` 封装。一次性建立"轻量化序列化 + 节流"规范，后续新接口沿用。

**完成情况：** `pytest backend/tests` **67 passed**（含新增 9 个用例：`test_benchmark.py` 分页包裹/lightweight/offset-limit 3 个、`test_profiles.py` 分页结构/flags 每请求一次 2 个、`test_services.py` systemctl 批量 1 个、`test_task_queue.py` 查询数常数/聚合统计 2 个、新建 `test_models_service.py` 下载节流 1 个）；`npm run build`（含 vue-tsc）通过。设计详见 `docs/batch3-design.md`。实现中自检发现并修正：批次 3 初版仅给 `benchmarks.list_jobs`/`profiles.list_profiles` 加了轻量化/flags，**遗漏了这两个接口的分页改造**（其余 3 接口已分页），前端解构 `data.items` 会拿到 undefined，已补齐。同时排查发现 `DashboardPage`/`ServicesPage`/`ObservationPage` 三个额外消费方也需适配，已一并处理。未引入新表/列/迁移，#11 Alembic 留待批次 5。

### 批次 4：前端工程化与体验（API 层 + 工具 + 测试 + 体验项）—— ✅ 已完成（2026-08-13）
> 合并原 F + I。API 抽象层是其他前端改动的前置地基，测试覆盖新建代码，体验项在此基础上推进。

| # | 事项 | 文件 | 说明 | 状态 |
|---|---|---|---|---|
| 17 | 前端 API 抽象层 | `src/api.ts` + `src/api/*` | 视图内联拼字符串 | ✅ 9 个业务模块 + 统一 client，API 层外直接调用为 0 |
| 18 | 深拷贝工具 | `src/utils.ts` | `JSON.parse(JSON.stringify())` | ✅ `structuredClone` 优先 + 兼容 fallback |
| 20 | 前端测试 + ESLint | Vitest / ESLint | 无测试无 lint | ✅ 54 tests；lint 0 error |
| 19 | 操作 busy 态 | 各 Page.vue | 无防重复提交 | ✅ `useBusy` 按操作 key 防重并绑定按钮 disabled |
| 10 | 队列 idle 慢轮询 | `useQueueStream.ts` | 轮询无退避 | ✅ SSE 正常推送；断线 running 1s / idle 5s 降级 |
| 16 | Excel 导出 Web Worker | `excelExporter.ts` / worker | writeBuffer 阻塞主线程 | ✅ 独立 Worker chunk |
| 22 | SSE 推送替代轮询 | 后端 + `TasksPage.vue` | 依赖 scheduler Condition | ✅ StreamingResponse + query token + 发布/订阅总线 |
| 21 | i18n | 全前端 | 文案硬编码 | ✅ vue-i18n + 中英文语言包 + 设置页切换 |

**一起做的理由：** #17 API 层 + #18 工具是"地基"；#20 测试覆盖工具函数与展示组件；#19/#10/#16 是交互稳定性与流畅度；#22/#21 在地基稳定后收尾。实际按 #17 → #18/#20 → #19 → #22/#10 → #16 → #21 推进。

**完成情况：** `npm run test` **54 passed**；`pytest backend/tests` **70 passed**；`npm run lint` **0 error / 13 warnings**；`npm run build`（含 vue-tsc）通过并生成独立 Excel Worker chunk。设计详见 `docs/batch4-design.md`。#25 前端分页已随批次 3 交付，不在本批次重复修改。

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
批次 1（日志/认证/健康）✅ 已完成 ─┬─> 批次 2（队列加固）✅ 已完成（依赖日志，已用 logger.exception / /ready）
                                └─> 批次 3 的调度异常排查也依赖日志（已满足）

批次 3（性能：N+1 + 分页 + 子进程/IO）✅ 已完成 ─> 批次 4 的 #25 前端分页（已随批次 3 同步改）

批次 4（前端工程化与体验）✅ 已完成
批次 5（架构重构 + 部署）   独立   <-- 下一步
```

**推荐落地顺序（考虑收益/依赖/风险）：**

1. **批次 1**：结构化日志 + 认证 + 健康检查（安全与可观测底座，被批次 2/3 依赖）—— ✅ **已完成**
2. **批次 2**：队列系统加固——孤儿回收 + 调度异常 + 并发锁 + stopping 语义（依赖批次 1 日志）—— ✅ **已完成**
3. **批次 3**：后端性能——N+1 序列化 + 分页 + systemctl 并行 + 下载节流（收益最大）—— ✅ **已完成**（#25 前端分页随本批次同步交付，批次 4 无分页阻塞）
4. **批次 4**：前端工程化与体验——API 层 + 工具 + 测试 + busy/轮询/Web Worker/SSE/i18n—— ✅ **已完成**
5. **批次 5**：架构重构与部署——Alembic + 拆分大文件 + 数据外置 + 容器化 CI—— **下一步**

> **关键洞察：** 批次 1–4 已连续完成安全、队列状态机、后端性能和前端工程化四层底座。当前剩余核心事项集中在批次 5：#3 冗余播种、#11 Alembic、#12 大文件拆分与数据外置、#23 容器化/CI，以及 #24 Prometheus 监控专项。

---

## 十二、批次 1 实施记录（2026-08-11）

### 已实现内容
对应 `docs/batch1-design.md`，关键交付：

- **结构化日志（#13）**：`backend/app/logging_config.py`（`JsonFormatter`/`setup_logging`/`get_logger`/`LOGGING_CONFIG`），`web.py` 传 `log_config` 给 uvicorn，`main.py` lifespan 调 `setup_logging()`。事件接入 systemctl/benchmark/download/queue dispatch/lifespan/未捕获异常。级别由 `LLAMALENS_LOG_LEVEL` 控制。
- **认证中间件（#1）**：`models.AuthSecret` 表（独立于 `AppSettings`）、`services/auth_service.py`（sha256 + compare_digest + loopback 判定）、`api/auth.py`（`verify_auth` 依赖 + `/auth/status` `/auth/login` `/auth/rotate`）。lifespan 引导 `LLAMALENS_API_TOKEN` → DB 哈希。前端 `LoginPage.vue` + `api.ts` 注入 `Authorization: Bearer` + 401 守卫。
- **健康检查（#24）**：`/health` 加 `SELECT 1` DB ping；新增 `/ready`（DB + `QueueScheduler.is_alive()`）；均免鉴权。

### 新增文件
- 后端：`app/logging_config.py`、`app/services/auth_service.py`、`app/api/auth.py`、`tests/test_auth_health_logging.py`
- 前端：`src/views/LoginPage.vue`

### 修改文件（关键）
- 后端：`main.py`（lifespan/依赖挂载/`/health`/`/ready`/全局异常处理器）、`web.py`、`models.py`（`AuthSecret`）、`schemas.py`、`services/systemd.py`、`services/benchmark.py`、`services/models_service.py`、`services/task_queue.py`（`is_alive` + dispatch 事件日志）
- 前端：`api.ts`、`router.ts`（`/login` + 守卫）、`main.ts`（启动 `/auth/status`）、`App.vue`、`stores/app.ts`、`views/SettingsPage.vue`（令牌轮换）、`styles.css`

### 实现中发现并修复的预存隐患
**`QueueScheduler.start()` 线程重启报错**：`__init__` 只创建一次 `threading.Thread`，`stop()` 后再次 `start()` 会抛 `RuntimeError: threads can only be started once`。此前因无 CI、测试未覆盖调度器生命周期而未暴露，被批次 1 新增的 client-fixture 测试与 `/ready` 触发。**最小修复**：`start()` 改为线程已死则重建、已活则幂等返回。**未触碰** `_loop` 的 `except Exception: pass`（#4，批次 2 边界）。

### 验证
- `pytest backend/tests` → **48 passed**（含新增 17 个 auth/health/logging 用例）
- `npm run build`（含 vue-tsc 类型检查）→ **通过**
- VS Code 诊断无错误

### 批次 1 边界（未做，留给后续批次）
- #4 `_loop` `except: pass` 修复、连续失败计数、队列 `error` 态 → 批次 2 ✅
- #14 队列并发写锁、#15 `stopping` 语义 → 批次 2 ✅
- #2 standalone benchmark / download 孤儿回收扩展 → 批次 2 ✅
- Prometheus 指标、SSE 推送、列表分页、Alembic、大文件拆分 → 各自后续批次

---

## 十三、批次 2 实施记录（2026-08-12）

### 已实现内容
对应 `docs/batch2-design.md`，关键交付：

- **孤儿任务回收（#2）**：`recover_on_startup()` 拆为 `_recover_queue_current_item` / `_recover_standalone_benchmarks` / `_recover_downloads` 三步。前两步把 `BenchmarkJob` 的 `running`/`queued` 标记 `failed` + `error="interrupted by restart"` + `finished_at`；第三步同处理 `DownloadJob` 并清理 `.part` 临时文件（`Path(target).with_suffix(suffix + ".part").unlink(missing_ok=True)`，失败仅 warning）。队列当前项删除、`current_item_id=None`、`status="idle"`。
- **调度线程异常处理（#4）**：删除 `_loop` 的 `except Exception: pass`，改为 `_handle_tick_failure(exc)`：`logger.exception("queue.tick_failed")` + 递增 `_consecutive_failures`。达阈值（`LLAMALENS_QUEUE_FAILURE_THRESHOLD`，默认 5）后 `_persist_error_state()` 把 `TaskQueue.status` 置 `error`（复用字符串列，不加表/列）。`_attempt_error_recovery()` 在每轮循环开始乐观恢复到 `_pre_error_status`；`_on_tick_success()` 清零计数。`diagnostics()` 暴露 `consecutive_failures`/`last_error`/`last_error_at`/`failure_threshold`，`serialize_queue` 附带、`/ready` 据此判 `degraded`。`POST /queue/reset` 手动复位（仅 `error` 态，非 `error` 返回 409）。
- **并发写锁（#14）**：模块级 `_queue_lock = threading.Lock()` 串行化 `start`/`pause`/`update_settings`/`enqueue`/`reorder`/`delete`/`stop_queue`/`reset`/`_try_dispatch`/`_handle_run_finished` 全部临界区；`run_benchmark_job(job_id)` 长任务锁外执行（与 `benchmark.EXECUTION_LOCK` 层级不同、互不嵌套）。`database._configure_sqlite` 追加 `PRAGMA busy_timeout=5000` 作跨会话防御。
- **stopping 语义（#15）**：`_handle_run_finished` 新增 `stopping_queue` 分支（当前项回 `waiting`、`last_run_id=None`、`started_at=None`、`q.status="idle"`）。新增 `stop_queue(db)` 服务 + `PATCH status=stop` 路由（仅 `running`/`stopping` 允许）。`delete_item` 当前项置 `stopping` 后 run 结束删除当前项、有 `waiting` 回 `running`、否则 `idle`。

### 新增文件
- 后端测试：`backend/tests/test_task_queue.py`（10 个用例）

### 修改文件（关键）
- 后端：`app/services/task_queue.py`（状态机核心重写）、`app/api/queue.py`（`PATCH status=stop` + `POST /reset`）、`app/schemas.py`（`QueuePatch.status` 加 `'stop'`）、`app/main.py`（`/ready` 扩展 `queue_status` + `scheduler_failures`）、`app/database.py`（`busy_timeout`）
- 前端：`src/types.ts`（`status` 加 `'stopping_queue'|'error'` + `scheduler` 字段）、`src/views/TasksPage.vue`（停止队列 / 复位队列按钮 + error 横幅 + 按钮文案）

### 实现中自检发现并修正的两处隐藏问题
1. **`error` 态卡死**：`error` 态下 `_tick` 因 `q.status not in ("running","stopping")` 提前 return，导致 `_on_tick_success` 永不被调用 → 队列永久卡在 `error`。**修正**：`_loop` 在每轮开始检查 `consecutive_failures >= threshold` 时先调 `_attempt_error_recovery()` 把状态乐观恢复到 `_pre_error_status`，使 `_tick` 能正常进入、成功后清零计数。
2. **重跑已 finished job**：若 `_handle_run_finished` 中途异常或被中断，下一轮 `_tick` 会用 `item.last_run_id` 重新提交已终态的 job。**修正**：`_tick` 内增加 job-terminal 守卫，`job.status in ("succeeded","failed","cancelled")` 时 `need_run=False`，直接走 finished 收尾。

### 验证
- `pytest backend/tests` → **58 passed**（含新增 10 个 `test_task_queue.py` 用例）
- `npm run build`（含 vue-tsc 类型检查）→ **通过**
- VS Code 诊断无错误

### 批次 2 边界（未做，留给后续批次）
- #6 `serialize_queue` 的 N+1（每项 `db.get` 两次 + session 全表扫）→ 批次 3 ✅
- #10 队列 idle 慢轮询 / SSE 推送 → 批次 4 ✅
- #11 Alembic 迁移（本批次用 `status` 字符串列规避了新列，迁移留待批次 5）
- Prometheus 指标、列表分页、大文件拆分 → 各自后续批次（列表分页已由批次 3 ✅）

---

## 十四、批次 3 实施记录（2026-08-12）

### 已实现内容
对应 `docs/batch3-design.md`，关键交付：

- **轻量化序列化（#5）**：`benchmarks.py` 的 `_serialize` 增加 `lightweight: bool = False` 参数，`lightweight=True` 时跳过 `job.attempts` 遍历重算，直接用 `summary_json` 中已有 metrics（job 完成时 `benchmark.py` 已写入 `summary_json["metrics"]["..."]["average"]`）。`list_jobs` 默认 `lightweight=True`，详情接口仍 `include_attempts`。
- **队列 N+1 批量化（#6）**：`task_queue.py` 的 `_serialize_item` 签名从 `(db, item)` 改为 `(item, task=None, job=None)`，不再内部 `db.get`；`serialize_queue` 用 `select(BenchmarkTask).where(id.in_(task_ids))` + `select(BenchmarkJob).where(id.in_(run_ids))` 批量预加载建 dict 映射；`session_stats` 改为 `SELECT status, COUNT(*) ... GROUP BY status` 聚合查询。每秒轮询查询数从 ~2N 降为常数 3 条。
- **flags 复用（#7）**：`profiles_service.py` 拆出 `_build_argv_with_flags(settings, config, known, canonical)` 接受预加载 flags；`list_profiles` 入口一次性加载 `known_flags`/`canonical_flags` 传入各 profile 复用（2N→2）。`serialize_profile` 增加 `flags` 参数。采用"每请求查一次"而非进程内缓存，避免失效与一致性问题。
- **systemctl 批量化（#8）**：`systemd.py` 新增 `list_units_status(pattern, timeout=30) -> dict[str, CommandResult]`，执行 `systemctl list-units pattern --output=json --all --no-pager` 一次拿全部单元状态，解析 JSON 按 unit 名建字典（失败或非 JSON 返回空字典 + warning）。`llama_services.serialize_service` 增加 `unit_status` 参数，传入时从字典取状态（不调子进程）；`services.py` 的 `list_services` 在 `with_status=True` 时调一次 `list_units_status("llamalens-*")`。N 次子进程降为 1 次。
- **下载节流（#9）**：`models_service.py` 新增 `_download_commit_interval_s()`（默认 2.0s，读 `LLAMALENS_DOWNLOAD_COMMIT_INTERVAL_MS`）和 `_download_commit_interval_bytes()`（默认 16MB，读 `LLAMALENS_DOWNLOAD_COMMIT_INTERVAL_BYTES`）。下载循环改为双维度节流：`if (now - last_commit_at >= commit_interval_s) or (written - last_commit_bytes >= commit_interval_bytes): db.commit()`；取消检查每 chunk 执行不节流（保证及时中断）。
- **列表分页（#25）**：5 个列表接口统一 `?offset&limit`（默认 offset=0/limit=50，limit 上限 200）+ `func.count()` total + `{items, total, offset, limit}` 包裹对象返回：
  - `benchmarks.list_jobs`（含 `task_id` 过滤）
  - `profiles.list_profiles`（移除 `response_model=list[ProfileOut]`）
  - `models.list_models`（含 `q`/`available_only` 过滤）、`models.list_downloads`
  - `tasks.list_tasks`

### 新增文件
- 后端测试：`backend/tests/test_models_service.py`（下载节流 commit 测试）

### 修改文件（关键）
- 后端：`api/benchmarks.py`（`_serialize` lightweight + `list_jobs` 分页）、`api/profiles.py`（flags 复用 + 分页）、`api/models.py`（list_models/list_downloads 分页）、`api/tasks.py`（list_tasks 分页）、`api/services.py`（list_units_status 调用）、`services/task_queue.py`（serialize_queue 批量化 + session_stats 聚合）、`services/profiles_service.py`（`_build_argv_with_flags`）、`services/systemd.py`（`list_units_status`）、`services/llama_services.py`（`serialize_service` unit_status）、`services/models_service.py`（下载节流）、`services/task_service.py`（list_tasks 分页参数）
- 前端：`views/ResultsPage.vue`（加载更多分页）、`views/ProfilesPage.vue`、`views/ModelsPage.vue`（含轮询下载列表）、`views/TasksPage.vue`（任务库列表）、`views/DashboardPage.vue`、`views/ServicesPage.vue`、`views/ObservationPage.vue` —— 全部适配解构 `data.items`

### 实现中自检发现并修正的问题
1. **遗漏分页改造**：批次 3 初版仅给 `benchmarks.list_jobs`（lightweight）/`profiles.list_profiles`（flags）加了非分页优化，但**未加 `?offset&limit` 分页**（其余 3 接口已分页）。前端已按 `{items, total, ...}` 改调用方式，但这两个后端接口仍返回数组，导致 `data.items` 为 undefined。**修正**：补齐两接口的 `offset`/`limit` Query 参数 + `func.count()` total + 包裹返回。
2. **遗漏前端消费方**：设计文档文件清单仅列 4 个视图，但排查发现 `DashboardPage.vue`（调 `/benchmarks`、`/profiles`）、`ServicesPage.vue`（调 `/profiles`、`/models`）、`ObservationPage.vue`（调 `/benchmarks`）三个额外消费方也需适配，否则运行时出错。**修正**：这三个页面传较大 limit（`?limit=200`，与原后端 limit(200) 行为一致）并解构 `.items`；ResultsPage 用真正的"加载更多"分页交互。

### 验证
- `pytest backend/tests` → **67 passed**（原 58 + 新增 9：`test_benchmark.py` 分页包裹/lightweight 用 summary/offset-limit 3 个、`test_profiles.py` 分页结构/flags 每请求只查一次 2 个、`test_services.py` systemctl 批量只调一次 list-units 1 个、`test_task_queue.py` 查询数不随 items 增长/聚合统计正确 2 个、`test_models_service.py` 60 chunk 仅 ≤6 次 commit 1 个）
- `npm run build`（含 vue-tsc 类型检查）→ **通过**
- VS Code 诊断无错误

### 批次 3 边界（未做，留给后续批次）
- #3 移除冗余 `seed_builtin_catalog` → 批次 5
- #10 队列 idle 慢轮询 / SSE 推送 → 批次 4 ✅
- #11 Alembic 迁移（本批次无 schema 变更，未涉及迁移）→ 批次 5
- #12 拆分 `benchmark.py` / `task_queue.py` → 批次 5
- #20 前端测试 + ESLint、#17 前端 API 抽象层 → 批次 4 ✅
- Web Worker Excel、i18n → 批次 4 ✅；Prometheus 指标仍待后续专项

---

## 十五、批次 4 实施记录（2026-08-13）

### 已实现内容

对应 `docs/batch4-design.md`，关键交付：

- **API 抽象层（#17）**：新建 `frontend/src/api/`，包含统一 `client.ts`、分页类型与 9 个业务模块。请求路径、HTTP 方法、query/body、响应类型、认证令牌、401 跳转及 AbortSignal 集中管理。`src/api.ts` 保留兼容入口并显式 re-export `./api/index`。
- **深拷贝工具（#18）**：`cloneConfig` 优先使用 `structuredClone`，仅保留 JSON fallback 兼容老浏览器；Profiles/Services 不再内联 JSON 深拷贝。
- **busy 防重（#19）**：新增 `useBusy()`，以操作 key 隔离状态；Tasks、Profiles、Services、Benchmark、Observation 的写操作接入，模板按钮同步 disabled。
- **前端测试与 lint（#20）**：引入 Vitest、Vue Test Utils、jsdom 与 ESLint flat config；覆盖 `metricsStats`、`chartAxis`、`excelExporter`、`utils`、`StatusBadge`。
- **SSE 与慢轮询降级（#22/#10）**：后端新增 `/api/v1/events/queue`、query token 认证和 scheduler 订阅/发布总线；前端 `useQueueStream` 使用 EventSource，断线后按运行状态 1s、空闲状态 5s 自适应轮询并自动重连。SSE keepalive 与订阅队列上限支持环境变量。
- **Excel Worker（#16）**：ExcelJS 的 workbook 序列化移至 `excelExport.worker.ts`；主线程仅收集数据、接收 Blob 并下载。
- **i18n（#21）**：引入 vue-i18n，新增中英文语言包和设置页语言切换；覆盖页面、共享 LaunchConfigEditor 与观测图表。

### 新增文件

- 后端：`app/api/events.py`、`tests/test_events.py`
- 前端：`src/api/*`、`src/composables/useBusy.ts`、`src/composables/useQueueStream.ts`、`src/config.ts`、`src/workers/excelExport.worker.ts`、`src/i18n/index.ts`、`src/i18n/locales/zh.json`、`src/i18n/locales/en.json`、`src/__tests__/*`、`vitest.config.ts`、`eslint.config.js`

### 实现中发现并修正的问题

1. **API 入口同名自引用导致全量构建失败**：项目同时存在 `src/api.ts` 与 `src/api/`，原兼容入口写成 `export * from './api'`，TypeScript 命中自身文件，页面导入的 `tasksApi` / `queueApi` 等全部显示未导出。修正为显式 `export * from './api/index'`，并补齐 Vite/tsconfig 的 `@` alias。
2. **SSE 空闲连接异常断开**：执行器中的 `queue.Queue.get(timeout=...)` 空闲时抛 `queue.Empty`，原实现只捕获 `asyncio.TimeoutError`，导致连接约 5 秒后异常结束。修正为同时捕获两者并发送 keepalive，新增初始事件、keepalive、publish、unsubscribe 测试。
3. **SSE composable 无法 stop 后重新 start**：`start()` 在 `stopped=true` 时直接 return，使显式停止后的重启失效。调整为仅在已有 EventSource 时返回，并在 start 时恢复运行状态。
4. **设计与现有 BenchmarkPage 行为存在差异**：当前 BenchmarkPage 只保存/入队后跳转 TasksPage，不再轮询 active job；因此队列 SSE 统一由 TasksPage 消费，不额外建立重复连接。

### 验证

- `npm run test` → **54 passed**（5 个测试文件）
- `pytest backend/tests` → **70 passed**（含新增 SSE 生命周期测试；1 条 Starlette TestClient 上游弃用 warning）
- `npm run lint` → **0 error / 13 warnings**
- `npm run build`（含 vue-tsc）→ **通过**；生成独立 `excelExport.worker-*.js` chunk
- API 层外直接请求扫描 → **0**
- `git diff --check` → **通过**

### 批次 4 边界

- 尚未在真实 Linux/systemd 部署环境完成浏览器断线重连、长时间 SSE 稳定性及大数据 Excel 导出的人工验收。
- ESLint warning 尚未清零：主要为 `LaunchConfigEditor` 受控表单直接编辑嵌套 prop；如需消除，应单独重构为 `modelValue`/emit 或显式本地副本。
- Prettier、后端 Ruff、CI、容器化与自动 E2E 未在本批次引入，归入批次 5 或后续质量专项。
