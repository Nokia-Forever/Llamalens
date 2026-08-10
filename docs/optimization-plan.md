# LlamaLens 优化设计方案

> 本文档基于对 LlamaLens 全栈项目（FastAPI 后端 + Vue 3 前端）的全面代码检查，整理出可落地的优化项。
> 所有事项均处于**设计阶段**，尚未实现。优先级按"严重程度 / 收益"排序。

---

## 一、项目现状概览

| 层 | 技术栈 | 评价 |
|---|---|---|
| 后端 | FastAPI + SQLAlchemy 2.0 + SQLite | 分层规范（api / services / models / schemas），安全意识较好（argv 数组执行、shlex 分词、路径校验、命令白名单） |
| 前端 | Vue 3 + TS + Vite + Pinia + ECharts | 路由懒加载、组件复用合理，但缺少 API 抽象层与测试 |
| 测试 | pytest（仅后端） | 核心逻辑有覆盖，但无前端测试、无 lint、无 CI |

整体属于一个**完成度较高的 MVP**，下面的优化按"严重程度 / 收益"排序。

---

## 二、高优先级：安全与正确性

### 1. 缺少任何认证/鉴权（最大风险）
应用以 root 运行，可写 `/etc/systemd/system`、调用 `systemctl`、发起下载、读取 journal，但 `backend/app/main.py` 中无任何 auth 中间件。README 与 `frontend/src/views/SettingsPage.vue` 都已承认此风险。

**设计方案：**
- 引入 FastAPI 依赖注入式的认证层：`APIKeyHeader` 或基于 `secrets.compare_digest` 的固定 token（写入 settings，非明文）。
- 新增 `AuthMiddleware` 或 `Depends(verify_token)`，在 settings 中存储 `api_token_hash`（仅存哈希）。
- 保留 loopback 默认免认证的开发模式，通过 `LLAMALENS_REQUIRE_AUTH=1` 控制。

### 2. 后台任务的"孤儿任务"问题
`backend/app/services/benchmark.py` 中 `BENCHMARK_EXECUTOR`（max_workers=1）与 `backend/app/services/models_service.py` 的 `EXECUTOR` 是进程内线程池。进程重启后，状态为 `running`/`queued` 的 job 永远停留在该状态，且取消集合 `_cancelled_jobs` 是内存态会丢失。

**设计方案：**
- 在 `lifespan` 启动时增加**孤儿任务回收**：扫描所有 `status in ('running','queued')` 的 BenchmarkJob / DownloadJob，标记为 `failed` 并写入 `error="进程重启，任务中断"`。
- 或引入轻量任务队列（如 SQLite 状态机 + 轮询 worker），但 MVP 阶段启动回收即可。

### 3. `list_arguments` 每次请求都重建种子目录
`backend/app/api/arguments.py` 的 `list_arguments`、`categories`、`refresh` 都调用 `seed_builtin_catalog(db)`，它对 `ArgumentCatalog` 全表扫描并 upsert。而 `backend/app/main.py` 的 `lifespan` 已经做过一次。

**设计方案：** 移除 API 层的 `seed_builtin_catalog` 调用，仅保留启动时播种 + `/arguments/refresh` 显式刷新。

---

## 三、高优先级：性能（N+1 与重复计算）

### 4. `list_jobs` 为每个 job 加载全部 attempts 重算均值
`backend/app/api/benchmarks.py` 的 `_serialize` 对每个 job 执行 `[attempt for attempt in job.attempts if ...]`，只为重算 `summary_json` 里已有的 `average`。列表返回 200 个 job 时，会触发 200 次 attempts 懒加载，是典型的 N+1 + 冗余计算。

**设计方案：**
- 列表接口直接返回 `json.loads(job.summary_json)` 中已有的 metrics，不再遍历 `job.attempts`。
- 仅在 `get_job(include_attempts=True)` 详情接口里才加载 attempts。
- 可给 `_serialize` 增加 `lightweight=True` 参数区分。

### 5. `list_profiles` 每个 profile 触发两次全表扫描
`backend/app/services/profiles_service.py` 的 `serialize_profile` → `build_launch_argv` → `known_flags(db)` + `canonical_flags(db)`，两者都对 `ArgumentCatalog` 全表扫描。N 个 profile = 2N 次扫描。

**设计方案：**
- 在 `list_profiles` 中一次性加载 `known_flags` 和 `canonical_flags`，传入 `serialize_profile` / `build_launch_argv` 复用。
- 或引入进程内缓存（带 TTL 或基于版本号失效），因为参数目录改动频率极低。

### 6. `list_services?with_status=true` 串行调用 systemctl
`backend/app/services/llama_services.py` 的 `serialize_service` 对每个 service 同步执行 `systemctl status` 子进程，N 个服务串行 N 次子进程，明显偏慢。

**设计方案：**
- 用 `ThreadPoolExecutor` 并行执行 `run_unit_action`（systemctl 调用是 IO/子进程等待，适合并发）。
- 或一次性 `systemctl list-units 'llamalens-*' --output=json` 批量获取状态，再与 DB 记录 join。

### 7. 下载进度逐 chunk commit
`backend/app/services/models_service.py` 的 `_run_download` 每 1MB chunk 都 `db.commit()` 一次，大文件下载会产生数千次磁盘写入。

**设计方案：** 按时间或字节节流提交（如每 2 秒或每 16MB 提交一次），结束时再 commit 终态。

---

## 四、中优先级：架构与可维护性

### 8. 手写迁移逻辑脆弱
`backend/app/database.py` 的 `_migrate_legacy_columns` 是一长串 `ALTER TABLE` + 多次 `inspect(engine)`，随 schema 演进会越来越难维护，且没有版本记录。

**设计方案：** 引入 Alembic 做正规迁移，初始 baseline 抽取当前 schema，后续改动走 migration 脚本，保留版本表 `alembic_version`。

### 9. 大文件拆分与职责分离
- `backend/app/services/benchmark.py`（~590 行）混合了 job 创建、执行编排、HTTP 测量、SSE 解析、资源采样、序列化。
- `backend/app/services/arguments.py` 的 `BUILTIN_ARGUMENTS`（113 项硬编码元组）内联在代码里。

**设计方案：**
- 拆 `benchmark.py` → `benchmark_runner.py`（编排）/ `measurement.py`（HTTP+SSE）/ `resource_sampler.py` / `benchmark_serializer.py`。
- 把 `BUILTIN_ARGUMENTS` 外置为 `app/data/builtin_arguments.json`，加载时校验，便于非代码贡献者维护。
- `serialize_service` 返回的庞大 dict 改为 Pydantic `LlamaServiceOut` 模型，兼顾输出校验与 OpenAPI 文档。

### 10. 缺少结构化日志
全项目无 `logging` 使用，subprocess 错误仅以字符串返回，生产排查困难。

**设计方案：** 配置 `structlog` 或标准 `logging`，统一 JSON 日志，记录：systemctl 调用 argv/returncode、benchmark 生命周期事件、下载事件、未捕获异常栈。

### 11. `EXECUTION_LOCK` 注释过时
`backend/app/services/job_control.py` 注释说"Profile 切换与 Benchmark 共用"，但当前只有 benchmark 用到，profile 切换代码已不存在该锁使用。

**设计方案：** 修正注释，或明确该锁的当前语义（串行化 benchmark 避免结果归属混乱）。

---

## 五、中优先级：前端优化

### 12. 缺少 API 客户端抽象层
每个视图都直接 `api<T>('/services?include_archived=true&with_status=true')` 内联拼字符串，路径分散、易错、无类型联动（路径与 `frontend/src/types.ts` 手动同步）。

**设计方案：** 新建 `src/api/services.ts` / `benchmarks.ts` 等，把端点封装为函数，返回强类型；视图只调用函数。例如 `listServices({ includeArchived: true })`。

### 13. 深拷贝用 `JSON.parse(JSON.stringify())`
`frontend/src/views/ServicesPage.vue`、ProfilesPage、LaunchConfigEditor 多处用此法克隆 LaunchConfig，丢失类型、对大对象慢、无法拷贝 Date（这里没 Date 暂可）。

**设计方案：** 抽一个 `cloneConfig` 工具函数，用 `structuredClone`（Node 17+/现代浏览器原生支持）或递归克隆。

### 14. 轮询策略粗糙，无实时推送
BenchmarkPage 每 1s 轮询、ModelsPage 每 2.2s 轮询下载，无退避、无停止条件优化。

**设计方案：**
- benchmark 状态用 SSE 推送（FastAPI `StreamingResponse` + `EventSourceResponse`），后端在 attempt 完成时推送增量。
- 短期低成本方案：轮询加指数退避 + 任务终态停止。

### 15. 部分操作无 busy 态
`frontend/src/views/ServicesPage.vue` 的 `archive`/`restore`/`remove` 未设 `busy`，点击后无防重复提交反馈。

**设计方案：** 统一加 `busy` 或抽 `useAsync` 组合式函数管理 loading/error。

### 16. 无前端测试、无 ESLint
`npm run build`（vue-tsc）是唯一检查，无单元测试、无 lint 规则。

**设计方案：**
- 加 Vitest + `@vue/test-utils`，覆盖 LaunchConfigEditor、api.ts、CSV 导出逻辑。
- 加 ESLint（flat config）+ Prettier，配 `npm run lint`。
- 后端 `backend/pyproject.toml` 加 `ruff` 配置。

### 17. i18n 缺失
所有 UI 文案硬编码中文。

**设计方案：** 引入 `vue-i18n`，抽取中文字符串为 locale 文件，为后续英文支持铺路（视产品诉求可选）。

---

## 六、低优先级：部署与可观测性

### 18. 无容器化、无 CI/CD
没有 Dockerfile、docker-compose、GitHub Actions，部署全靠手工。

**设计方案：**
- 多阶段 `Dockerfile`（前端 build + 后端 slim 镜像）。
- GitHub Actions：`pytest` + `npm run build` + lint，PR 必过。
- `docker-compose.yml` 带卷挂载（data 目录）。

### 19. 健康检查与可观测性薄弱
`/api/v1/health` 只返回 `{"status":"ok"}`，未检查 DB 或 systemd 可达性。

**设计方案：**
- `/health` 增加 DB ping；新增 `/ready` 区分存活与就绪。
- 可选暴露 Prometheus metrics（请求耗时、systemctl 调用次数、任务队列深度）。

### 20. 列表接口无分页
`list_jobs`（limit 200）、`list_profiles`、`list_models` 均无分页。

**设计方案：** 统一 `?offset&limit` 分页参数 + 总数返回，前端 ResultsPage 加无限滚动或分页器。

---

## 七、优化实施优先级建议

| 优先级 | 事项 | 预期收益 | 复杂度 |
|---|---|---|---|
| P0 | #1 认证中间件 | 消除最大安全风险 | 中 |
| P0 | #2 孤儿任务回收 | 修复数据正确性 | 低 |
| P0 | #3 移除冗余 seed_builtin_catalog | 减少 API 延迟 | 低 |
| P0 | #4 list_jobs 不重算均值 | 列表性能数十倍提升 | 低 |
| P1 | #5 list_profiles 复用 flags 查询 | 列表性能提升 | 低 |
| P1 | #6 systemctl 并行/批量状态 | 服务列表响应变快 | 中 |
| P1 | #10 结构化日志 | 可运维性 | 中 |
| P1 | #16 ESLint + Vitest | 前端质量基线 | 中 |
| P2 | #8 Alembic 迁移 | 长期可维护 | 中高 |
| P2 | #9 拆分 benchmark.py | 可维护 | 中 |
| P2 | #12 前端 API 抽象层 | 可维护 | 中 |
| P2 | #18 Dockerfile + CI | 部署标准化 | 中 |
| P3 | #14 SSE 推送、#17 i18n、#19 监控 | 体验/可观测 | 高 |

---

## 八、实施路径建议

1. **第一阶段（P0 快速收益）：** 完成 #2、#3、#4，低复杂度、高收益，可在一轮迭代内交付。
2. **第二阶段（安全基线）：** 完成 #1 认证中间件，配合 README 的风险说明形成完整方案。
3. **第三阶段（P1 性能与可维护）：** #5、#6、#10、#16，建立日志与前端测试基线。
4. **第四阶段（架构演进）：** #8、#9、#12、#18，为长期维护打基础。
5. **第五阶段（体验增强）：** #14、#17、#19、#20，按产品诉求推进。

每个阶段完成后建议运行现有测试（`pytest backend/tests` + `npm run build`）回归验证，避免引入回归。
