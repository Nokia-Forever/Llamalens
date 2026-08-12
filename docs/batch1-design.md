# LlamaLens 批次 1 设计文档：结构化日志 + 认证中间件 + 健康检查

> 本文档是 **设计阶段**，不含最终实现代码。对应 `optimization-plan.md` 的批次 1（#13 / #1 / #24）。
> 关键决策已于评审中确认，文末列出具“不在批次 1 范围”的项，避免与批次 2+ 冲突。

---

## 一、本设计解决什么问题

批次 1 聚焦“安全 + 可观测底座”。当前项目存在三个互相叠加的隐患：

### 问题 A（#13）：全项目无任何日志，调度线程静默吞异常

- 后端代码全文无 `import logging` / `logger` / `structlog`（已搜索确认）。
- `backend/app/services/task_queue.py` 的 `QueueScheduler._loop`（[task_queue.py:308-315](file:///d:/user/worker/LlamaLens/backend/app/services/task_queue.py#L308-L315)）存在：
  ```python
  except Exception:
      pass
  ```
  若 `_tick()` 因 SQLite 锁、代码 bug 反复失败，会**无限空转且无任何日志**，故障完全不可见。
- systemctl 调用、benchmark 生命周期、下载任务、启动回收等关键事件均无结构化记录，运维只能靠猜。
- `app/web.py` 通过 `uvicorn.run("app.main:app", ...)` 启动（[web.py:18](file:///d:/user/worker/LlamaLens/backend/app/web.py#L18)），uvicorn 自带 access log，但与应用事件未统一格式。

> **本批次只建立日志基础设施 + 在低变动点接入事件日志。** `task_queue._loop` 的 `except: pass` 修复、连续失败计数、队列 `error` 态属 **#4（批次 2）**，本批次不触碰，仅为其铺好日志通道。

### 问题 B（#1）：无任何认证，应用以 root 运行

- `backend/app/main.py` 仅有 `CORSMiddleware`，无 auth 中间件、无 `Depends(verify_token)`（[main.py:44-50](file:///d:/user/worker/LlamaLens/backend/app/main.py#L44-L50)）。
- 应用以 root 运行，可写 `/etc/systemd/system`、调用 `systemctl`、发起大文件下载、读取 journal（README “Web 暴露风险”一节已明确警示）。
- 配置体系：`AppSettings`（Pydantic 模型，[schemas.py:9-23](file:///d:/user/worker/LlamaLens/backend/app/schemas.py#L9-L23)）以 JSON 存于 DB `SettingsRecord(id=1)`（[settings_service.py](file:///d:/user/worker/LlamaLens/backend/app/services/settings_service.py)），当前无任何令牌字段。
- 前端为同源 SPA：单一 `api<T>()` fetch 封装（[api.ts](file:///d:/user/worker/LlamaLens/frontend/src/api.ts)），便于统一注入 `Authorization` 头；路由在 [router.ts](file:///d:/user/worker/LlamaLens/frontend/src/router.ts)，应用入口 [main.ts](file:///d:/user/worker/LlamaLens/frontend/src/main.ts)。

### 问题 C（#24）：健康检查过于薄弱

- `/api/v1/health` 直接定义在 `main.py`（[main.py:53-55](file:///d:/user/worker/LlamaLens/backend/app/main.py#L53-L55)），只返回 `{"status": "ok"}`，无 DB ping、无就绪判断、无调度线程存活。
- 部署侧（systemd / 容器探针）无法据实判断“是否真正就绪”。

---

## 二、目标与非目标

### 目标
1. 建立统一的 **标准库 `logging` + JSON 格式** 日志通道，覆盖应用与 uvicorn access log。
2. 在 systemctl / benchmark 生命周期 / 下载 / 鉴权 / 启动生命周期 / 未捕获异常等关键点接入结构化日志；为队列调度**正常事件**接入日志（#13 范围）。
3. 引入 **API 令牌认证**：env 引导 + DB 哈希存储，支持免重启轮换；loopback 默认免认证，可强制。
4. 前端提供 **登录页 + localStorage** 鉴权交互，`api.ts` 自动附加头并在 401 时回登录页。
5. `/health` 增加 DB ping；新增 `/ready`（含调度线程存活判断）；探针免鉴权。

### 非目标（明确不在批次 1）
- #4 `task_queue._loop` 的 `except: pass` 修复、连续失败计数、队列 `error` 态 → 批次 2。
- #14 队列并发写锁、#15 `stopping` 语义 → 批次 2。
- #2 standalone benchmark / download 的孤儿回收 → 批次 2。
- Prometheus 指标（队列深度、请求耗时、systemctl 计数）→ 后续专门迭代。
- 多用户/RBAC、JWT、OAuth —— 单令牌即可。
- 列表分页、Alembic、大文件拆分 → 各自后续批次。

---

## 三、关键设计决策（已确认）

| 维度 | 决策 | 理由 |
|---|---|---|
| 日志库 | **标准库 `logging` + 自定义 JSON formatter** | 零新三方依赖（`pyproject.toml` 当前极简）；`dictConfig` 即可统一应用与 uvicorn 日志；满足事件结构化需求。 |
| 令牌存储 | **混合：env 引导 + DB 哈希** | `LLAMALENS_API_TOKEN` 环境变量启动时写入 DB 哈希（仅存哈希）；运行时校验走 DB，可通过 `/auth/rotate` 免重启轮换。无 env 且 DB 无令牌时不启用鉴权（向后兼容）。 |
| 前端鉴权 | **登录页 + localStorage** | 新增 `/login` 路由与 `LoginPage.vue`；`api.ts` 从 localStorage 读令牌附加 `Authorization: Bearer`；401 清除令牌并回登录页。 |
| 可观测范围 | **仅 `/health` + `/ready`** | 批次 1 聚焦底座；Prometheus 延后，避免批次膨胀。 |

---

## 四、模块 A：结构化日志（#13）

### 4.1 配置架构

新增 `backend/app/logging_config.py`，导出：
- `LOGGING_CONFIG: dict` —— 供 `web.py` 传给 `uvicorn.run(..., log_config=LOGGING_CONFIG)`。
- `setup_logging(level: str | None = None) -> None` —— 幂等 `dictConfig`，供 lifespan / 测试场景调用。

`dictConfig` 结构（设计示意）：

```python
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "app.logging_config.JsonFormatter"},
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
        }
    },
    "loggers": {
        "app": {"level": "INFO", "handlers": ["stdout"], "propagate": False},
        "uvicorn": {"level": "INFO", "handlers": ["stdout"], "propagate": False},
        "uvicorn.access": {"level": "INFO", "handlers": ["stdout"], "propagate": False},
        "sqlalchemy": {"level": "WARNING"},
    },
    "root": {"level": "INFO", "handlers": ["stdout"]},
}
```

要点：
- 统一输出 **stdout**，由 systemd journal / 容器日志驱动自动接管。
- 日志级别由环境变量 `LLAMALENS_LOG_LEVEL`（默认 `INFO`）覆盖 root 与 `app` logger。
- `uvicorn` / `uvicorn.access` 接入同一 JSON formatter，避免双格式。
- `sqlalchemy` 置 `WARNING`，抑制引擎噪声。
- 现有 `web.py` 的 `uvicorn.run(..., proxy_headers=True)` 增补 `log_config=LOGGING_CONFIG`。

### 4.2 JSON formatter 设计

自定义 `JsonFormatter(logging.Formatter)`（无新依赖），输出字段：

| 字段 | 说明 |
|---|---|
| `ts` | ISO8601 UTC 时间戳 |
| `level` | `INFO`/`WARNING`/`ERROR` 等 |
| `logger` | logger 名（如 `app.services.task_queue`） |
| `event` | 事件标识（如 `systemctl.invoke`、`benchmark.finished`、`auth.failed`） |
| `msg` | 人类可读消息（`record.getMessage()`） |
| `**extra` | `logger.info(..., extra={...})` 传入的结构化字段平铺 |

异常栈以 `exc_info` 字段输出多行字符串。**令牌明文绝不进日志**（见 §八）。

### 4.3 logger 获取约定

- 统一：`from app.logging_config import get_logger`；`logger = get_logger(__name__)`。
- 事件使用 `logger.info("event_name", extra={...})`，`event_name` 用点分动词式命名。

### 4.4 关键事件清单（接入点）

| 事件 | 级别 | 落点文件 | 上下文字段 |
|---|---|---|---|
| `lifespan.starting` / `lifespan.stopped` | INFO | `main.py` lifespan | `seed_ok`, `migrate_ok` |
| `systemctl.invoke` / `systemctl.result` | INFO | `services/systemd.py` | `argv`, `returncode`, `scope`, `stderr`(截断) |
| `benchmark.created` / `started` / `finished` / `failed` / `cancelled` | INFO/WARN | `services/benchmark.py` | `job_id`, `service_id`, `model_alias`, `run_count` |
| `download.start` / `progress` / `finished` / `failed` | INFO/WARN | `services/models_service.py` | `job_id`, `url`(脱敏域名), `bytes`, `total` |
| `queue.dispatch` / `queue.item_started` / `queue.item_finished` | INFO | `services/task_queue.py` | `item_id`, `task_id`, `run_id` |
| `auth.failed` / `auth.no_token` / `auth.loopback_exempt` | INFO/WARN | 鉴权依赖（§五） | `path`, `client_host`(脱敏), `reason` |
| `auth.token_bootstrapped` / `auth.token_rotated` | INFO | `main.py` lifespan / `/auth/rotate` | 无令牌明文 |
| `uncaught_exception` | ERROR | 全局异常处理（§4.5） | `path`, `exc_type` |

> 队列调度事件的 **正常生命周期** 在批次 1 接入；`except: pass` 的修复与失败计数属 #4（批次 2），本批次不动该 except。

### 4.5 未捕获异常处理

在 `main.py` 注册 FastAPI 异常处理器 / 轻量中间件，对未处理异常 `logger.exception("uncaught_exception", extra={"path": ...})` 后再抛出，确保栈进结构化日志。HTTP 422（校验错误）等可降级为 DEBUG/INFO，避免噪声。

### 4.6 测试与 caplog
- `pytest` 默认不强制 JSON（`setup_logging` 幂等，caplog 通过 propagate 捕获）；现有 `conftest.py` 不需改动。
- 新增少量日志断言用例（如 systemctl 调用产生 `systemctl.result` 事件）。

---

## 五、模块 B：认证中间件（#1）

### 5.1 令牌存储模型

**不把令牌哈希放进 `AppSettings`**，否则 `GET /api/v1/settings` 会回显哈希（信息泄露）。改为**新增独立表**：

```python
class AuthSecret(Base):
    __tablename__ = "auth_secrets"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)  # 单行 id=1
    token_hash: Mapped[str] = mapped_column(String(128), default="")
    updated_at: Mapped[datetime]
```

理由：
- 新表由 `init_db()` 的 `Base.metadata.create_all` 自动创建，无需触碰手写迁移 `_migrate_legacy_columns`（新列才需 ALTER）。
- 与用户可见设置隔离，`GET /settings` 不暴露。

### 5.2 哈希算法

- 令牌为高熵随机串，`hashlib.sha256(token.encode("utf-8")).hexdigest()` 足够（API token 场景无需慢哈希）。
- 比对用 `secrets.compare_digest(stored_hash, computed_hash)`，避免时序泄露。
- 可选硬化：`hashlib.scrypt`（若未来放宽令牌熵假设）——本批次不做。

### 5.3 启动引导（lifespan）

在 `main.py` 的 `lifespan` 中，`init_db()` 之后、`task_queue` 启动之前：

```
token_env = os.getenv("LLAMALENS_API_TOKEN", "").strip()
if token_env:
    upsert AuthSecret(id=1, token_hash=sha256(token_env), updated_at=now)
    logger.info("auth.token_bootstrapped")   # 不记明文
# 否则：保留 DB 既有哈希；若 DB 也无 → 鉴权关闭（向后兼容）
```

语义：
- env 仅作**引导/覆盖**：env 非空则覆盖 DB 哈希；env 为空时沿用 DB 哈希（实现“改 env 重启即轮换”与“DB 轮换免重启”并存）。
- 无 env 且 DB 无哈希 → 鉴权关闭（与现状一致，保护现有本地部署与测试）。

### 5.4 loopback 与强制策略

- `LLAMALENS_REQUIRE_AUTH`：`"1"` 时即使 loopback 也强制鉴权；默认（未设/`"0"`）loopback 免认证。
- **loopback 判定基于 `request.client.host`**（`127.0.0.1` / `::1` / `localhost`），**不信任 `X-Forwarded-For`**，防止远程伪造。
- 令牌已配置时，非 loopback 请求一律需鉴权；令牌未配置时，鉴权整体关闭（向后兼容，但 `0.0.0.0` 绑定仍属用户自担风险，README 已警示）。

### 5.5 鉴权依赖 `verify_auth`

采用 **FastAPI 依赖**（而非中间件），理由：复用 `get_db` 会话、对每个 router 显式可控、易于 `TestClient` 测试。

```python
def verify_auth(request: Request, db: Session = Depends(get_db)) -> None:
    if request.url.path in EXEMPT_PATHS:
        return
    host = request.client.host if request.client else ""
    loopback = host in ("127.0.0.1", "::1", "localhost")
    require = os.getenv("LLAMALENS_REQUIRE_AUTH", "0") == "1"
    if loopback and not require:
        logger.info("auth.loopback_exempt", extra={"path": request.url.path})
        return
    secret = db.get(AuthSecret, 1)
    if not secret or not secret.token_hash:
        return  # 鉴权未启用
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if token and secrets.compare_digest(secret.token_hash, sha256(token)):
        return
    logger.warning("auth.failed", extra={"path": request.url.path, "reason": "missing_or_invalid"})
    raise HTTPException(status_code=401, detail="unauthorized")
```

挂载方式（`main.py`）：

```python
API_DEPS = [Depends(verify_auth)]
for router in [settings, system, services, arguments, models, profiles, benchmarks, tasks, queue]:
    app.include_router(router, prefix="/api/v1", dependencies=API_DEPS)
# health / ready / auth 路由单独 include，不带 API_DEPS
```

### 5.6 免鉴权路径清单

| 路径 | 是否免鉴权 | 说明 |
|---|---|---|
| `/api/v1/health` | 免 | liveness 探针 |
| `/api/v1/ready` | 免 | readiness 探针 |
| `/api/v1/auth/status` | 免 | 前端启动前判断是否需登录 |
| `/api/v1/auth/login` | 免 | 登录本身 |
| `/api/v1/auth/rotate` | **需鉴权** | 已登录用户轮换令牌 |
| 其余 `/api/v1/*` | 需鉴权（当令牌已配置且非 loopback 豁免） | |

### 5.7 `/auth` router 设计

新增 `backend/app/api/auth.py`：

| 方法 | 路径 | 入参 | 行为 | 返回 |
|---|---|---|---|---|
| GET | `/auth/status` | — | 计算当前调用方是否需鉴权 | `{auth_required: bool}` |
| POST | `/auth/login` | `{token: str}` | 比对 DB 哈希 | 成功 `{ok: true}`；失败 401 |
| POST | `/auth/rotate` | `{new_token: str}` | 校验调用方已鉴权；更新 DB 哈希 | `{ok: true, updated_at}` |

- `auth_required` 计算（与 `verify_auth` 同源逻辑，抽公共函数）：
  - loopback 且未强制 → `false`；
  - 否则 `bool(AuthSecret.token_hash)`。
- `/auth/login` 与 `/auth/rotate` 接收**明文令牌**，服务端哈希后比对/存储；**全程不记录明文**。
- 暴力破解：高熵令牌难以爆破，本批次**不实现限流**（留作可选硬化：每 IP 失败计数 + 指数退避，后续迭代）。

### 5.8 前端登录页 + localStorage

- 新增 `frontend/src/views/LoginPage.vue` 与路由 `/login`（`router.ts` 增加 `{ path: '/login', ... }`）。
- 应用启动守卫（`main.ts` 或 `App.vue` 顶层）：
  1. 调 `GET /auth/status`；
  2. 若 `auth_required=false` → 直接进入应用；
  3. 若 `auth_required=true` 且 `localStorage` 无 `llamalens_token` → 跳 `/login`；
  4. 有令牌 → 进入应用（后续请求带令牌，若无效由 401 守卫处理）。
- `api.ts` 改造：
  ```ts
  const token = localStorage.getItem('llamalens_token')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  // 响应 401：
  localStorage.removeItem('llamalens_token')
  location.assign('/login')
  ```
- `LoginPage.vue`：`POST /auth/login {token}`；成功 `localStorage.setItem('llamalens_token', token)` 后跳 `/`。
- 设置页可加“轮换令牌”入口（调 `/auth/rotate`），属体验增强，可在批次 1 末尾或后续做。

### 5.9 测试影响
- `conftest.py` 默认无 `AuthSecret` 行 → 鉴权关闭，**现有用例保持绿**。
- 新增鉴权用例：插入哈希后测 401（无头）/ 200（正确头）/ loopback 免认证 / `LLAMALENS_REQUIRE_AUTH=1` 强制。
- `/auth/status`、`/auth/login`、`/auth/rotate` 各加用例。

---

## 六、模块 C：健康检查与就绪（#24）

### 6.1 `/health`（liveness）
- 保留免鉴权；返回值升级为：
  ```json
  {"status": "ok", "db": "ok"}
  ```
- DB ping：`db.execute(text("SELECT 1"))`，失败时 `db` 为 `"fail"` 且 `status` 仍 `ok`（进程活，DB 暂不可用，交由 `/ready` 判就绪）。
- 可从 `main.py` 迁入 `api/system.py` 或保留原位（设计建议迁入 `system.py`，与系统类接口同处）。

### 6.2 `/ready`（readiness）
- 新增 `GET /api/v1/ready`（免鉴权），返回：
  ```json
  {
    "status": "ready",
    "checks": {
      "db": "ok",
      "scheduler_alive": true
    }
  }
  ```
- `status`：`ready`（DB ok 且调度线程存活）/ `degraded`（任一不达标，但进程可服务）。
- DB ping 同上；`scheduler_alive` 取 `get_scheduler().is_alive()`。

### 6.3 调度线程健康暴露（仅线程存活）
- `QueueScheduler` 增加 `is_alive(self) -> bool`：`return self._thread.is_alive()`。
- **不**在本批次加入“连续失败计数 / `last_error` / 队列 `error` 态”——这些属 #4（批次 2）。批次 2 完成后可扩展 `/ready` 的 `checks` 增加 `scheduler_failures`。

### 6.4 探针免鉴权
- `/health`、`/ready` 进 `EXEMPT_PATHS`，供 systemd / 容器探针直连。

---

## 七、配置与环境变量变更

| 变量 | 默认 | 作用 |
|---|---|---|
| `LLAMALENS_API_TOKEN` | （空） | 启动引导令牌；非空时写入 DB 哈希 |
| `LLAMALENS_REQUIRE_AUTH` | `0` | `1` 时强制 loopback 也鉴权 |
| `LLAMALENS_LOG_LEVEL` | `INFO` | root / app logger 级别 |

令牌生成建议（部署文档补充）：
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## 八、安全考量

1. **令牌不落库明文**：DB 仅存 sha256 哈希；env 仅启动期存在于进程环境。
2. **令牌明文不进日志**：`auth.failed` 仅记 `reason`/`path`；`bootstrap`/`rotate` 只记事件本身。
3. **时序安全**：`secrets.compare_digest` 比对哈希。
4. **loopback 不可伪造**：基于 `request.client.host`，不取 `X-Forwarded-For`。
5. **前端 localStorage 风险**：令牌存 localStorage 有 XSS 风险；本工具自托管、无第三方脚本，风险可接受；后续可换 `HttpOnly` Cookie + CSRF 令牌（非本批次）。
6. **`0.0.0.0` 绑定**：未配置令牌时仍裸奔，README 已警示；启用令牌后远程即受保护。
7. **`/auth/login` 暴力破解**：高熵令牌难爆破，本批次不限流（可选硬化见 §5.7）。

---

## 九、文件改动清单（设计层面，不含实现）

### 后端新增
- `backend/app/logging_config.py` —— `LOGGING_CONFIG` / `setup_logging` / `get_logger` / `JsonFormatter`
- `backend/app/api/auth.py` —— `/auth/status` `/auth/login` `/auth/rotate`
- `backend/app/services/auth_service.py` —— `AuthSecret` 读写、`is_auth_required()`、`hash_token()`、`verify_token()` 公共逻辑

### 后端修改
- `backend/app/main.py` —— lifespan 引导令牌、注册 `verify_auth` 依赖、`setup_logging()`、`/health` 升级、新增 `/ready`、include `auth` router
- `backend/app/web.py` —— `uvicorn.run(..., log_config=LOGGING_CONFIG)`
- `backend/app/models.py` —— 新增 `AuthSecret` 模型
- `backend/app/services/systemd.py` —— systemctl 调用前后 `logger.info("systemctl.*")`
- `backend/app/services/benchmark.py` —— 生命周期事件日志
- `backend/app/services/models_service.py` —— 下载事件日志
- `backend/app/services/task_queue.py` —— **仅**正常 dispatch 事件日志 + `is_alive()`；**不动** `except: pass`
- `backend/app/api/system.py` —— 视情况承接 `/health` `/ready`（或保留 `main.py`）

### 前端新增
- `frontend/src/views/LoginPage.vue`
- `frontend/src/api/auth.ts`（可选封装 `status/login/rotate`）

### 前端修改
- `frontend/src/router.ts` —— 增加 `/login` 路由 + 启动守卫
- `frontend/src/api.ts` —— 注入 `Authorization` 头 + 401 守卫
- `frontend/src/main.ts` 或 `App.vue` —— 启动期 `/auth/status` 检查
- `frontend/src/views/SettingsPage.vue` ——（可选）令牌轮换入口

---

## 十、依赖变更
- **后端无新增三方依赖**（`logging` / `hashlib` / `secrets` 均为标准库）。
- 前端无新增依赖。

---

## 十一、兼容性与回滚
- 未配置令牌（无 env、DB 无 `AuthSecret`）→ 鉴权关闭，行为与现状一致；现有 `pytest` 全绿。
- 日志启用后，未设置 `LLAMALENS_LOG_LEVEL` 默认 INFO，不影响功能。
- 回滚：移除 `verify_auth` 依赖与 `AuthSecret` 表、还原 `/health`、卸载 `log_config`，即可回到 v1 行为。

---

## 十二、验证计划（实现后执行）
1. `python -m pytest backend/tests` 全绿（含新增鉴权 / 日志 / 健康检查用例）。
2. `cd frontend && npm run build` 通过。
3. 手动：
   - 设 `LLAMALENS_API_TOKEN`，远程无头 → 401；带 `Authorization: Bearer` → 200。
   - loopback 默认免认证；`LLAMALENS_REQUIRE_AUTH=1` 时 loopback 也需头。
   - `/auth/status`、登录页、401 回跳流程闭环。
   - `/health` 返回 `db: ok`；`/ready` 返回 `scheduler_alive: true`。
   - 触发一次 systemctl 调用，确认 journal 中出现 `systemctl.result` JSON 记录。

---

## 十三、批次 1 内部实施顺序
1. **日志基础设施**：`logging_config.py` + `web.py` 接入 + `main.py` lifespan `setup_logging()`。
2. **事件日志接入**：systemd / benchmark / download / lifespan / 未捕获异常 / 队列 dispatch 正常事件。
3. **认证底座**：`AuthSecret` 表 + 哈希/比对 + lifespan 引导 + `verify_auth` 依赖 + `/auth` router。
4. **健康检查**：`/health` 升级 + `/ready` + `QueueScheduler.is_alive()`。
5. **前端**：`api.ts` 头 + 401 守卫 → `LoginPage.vue` + 路由 → 启动 `/auth/status` 守卫。

每个子步骤后回归：`pytest backend/tests` + `npm run build`。

---

## 十四、显式不在批次 1 范围（避免与批次 2+ 冲突）
- #4 `task_queue._loop` `except: pass` 修复、连续失败计数、队列 `error` 态 → 批次 2。
- #14 队列并发写锁、#15 `stopping` 语义 → 批次 2。
- #2 standalone benchmark / download 孤儿回收扩展 → 批次 2。
- Prometheus 指标、SSE 推送、列表分页、Alembic、大文件拆分 → 各自后续批次。

> 批次 1 完成后，日志通道与认证/健康底座就位，批次 2 可直接用 `logger.exception` 改造调度线程异常处理，并用 `/ready` 扩展失败计数。
