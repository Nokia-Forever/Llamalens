# 批次 4 设计文档：前端工程化与实时体验

> 本文档对应 `docs/optimization-plan.md` 第十节"批次 4"。本批次聚焦前端工程化基础设施（API 抽象层 / 工具函数 / 测试 / lint）与实时交互体验（SSE 推送 / busy 防重 / Excel 非阻塞 / i18n）。**本文件仅做设计，不包含实现。**

---

## 一、问题说明（解决什么问题）

批次 1–3 完成了后端的安全底座、队列加固与性能优化，但前端仍停留在"能跑"的原始状态，存在以下系统性缺陷：

### 1.1 API 调用散落、无抽象层（#17）
10 个 `.vue` 页面里散落着 **74 处**直接拼字符串调接口的内联代码，例如：
```ts
// TasksPage.vue 内联调用示例
const data = await api<TaskQueueState>('/queue')
await api('/queue', { method: 'PATCH', ...jsonBody({ status: 'start' }) })
```
问题：
- 路径字符串（`'/queue'`、`'/benchmarks'`）与 HTTP 方法、请求体结构分散在视图里，后端路由变更时需全局搜索替换，极易遗漏。
- 响应类型（如 `TaskQueueState`、`{items,total,offset,limit}`）在各调用点重复手写，分页包裹结构（批次 3 引入）尤其易写错。
- 无统一错误处理/重试/取消逻辑，每个 `.vue` 各自 try/catch + `store.notify`。
- 轮询请求（TasksPage 1s、ModelsPage 2.2s）无法在组件卸载时统一取消（无 AbortController）。

### 1.2 深拷贝用 JSON hack（#18）
`ProfilesPage.vue`、`ServicesPage.vue` 用 `JSON.parse(JSON.stringify(obj))` 做深拷贝（2 处）。问题：无法处理 `Date`、`Map`、`Set`、`undefined`、循环引用；性能差；语义模糊。

### 1.3 操作无 busy 防重（#19）
`TasksPage.vue` 仅有一个全局 `acting` ref（且未区分操作），`deleteItem`/`reorder` 等操作无独立 busy 标记，用户可连续点击触发重复请求。`ObservationPage.vue` 的 Excel 导出虽有 `exporting` ref 但按钮 disabled 状态未绑定。其余页面（ProfilesPage/ServicesPage/BenchmarkPage）的写操作（create/update/delete/deploy）普遍缺少防重复提交保护。

### 1.4 零测试、零 lint（#20）
前端无任何自动化测试，`metricsStats.ts`（统计聚合）、`chartAxis.ts`（轴布局）、`excelExporter.ts`（Excel 生成）等纯函数完全无覆盖。无 ESLint/Prettier，代码风格无强制基线。

### 1.5 轮询无退避（#10）
`TasksPage.vue` 固定 1s 轮询 `/queue`，即使队列 idle（无任务、无运行中 job）也每秒发请求。`ModelsPage.vue` 固定 2.2s 轮询下载进度。无自适应退避策略。

### 1.6 Excel 导出阻塞主线程（#16）
`excelExporter.ts` 的 `exportObservationExcel()` 在主线程同步执行 `workbook.xlsx.writeBuffer()`，大数据集（数百 job × 多 attempts）导出时 UI 冻结数秒，进度条无法刷新。

### 1.7 无实时推送（#22）
后端无 SSE/WebSocket 基础设施。前端全靠轮询感知队列状态变更（任务启动/完成/失败），延迟 ≥1s 且产生大量无效请求。后端 `QueueScheduler` 已有 `threading.Condition` + `notify()` 机制（8 处状态变更点都调 `notify()`），但事件仅用于唤醒 scheduler 线程，未对外暴露。

### 1.8 无国际化（#21）
全部文案硬编码中文，无 i18n 框架。无法支持英文或其他语言。

---

## 二、目标

1. **建立前端 API 抽象层**：按后端模块封装强类型函数，消除 74 处内联调用，路径/类型/错误处理集中维护。
2. **消除 JSON hack**：提供语义化的 `cloneConfig` 深拷贝工具。
3. **统一 busy 防重**：所有写操作有独立 busy 标记，防重复提交。
4. **建立测试与 lint 基线**：Vitest 覆盖纯函数，ESLint 强制代码风格。
5. **SSE 实时推送**：后端新增 `/events` SSE 端点 + scheduler 事件总线，前端 TasksPage/BenchmarkPage 改用 EventSource。
6. **慢轮询降级**：SSE 断线时自动降级为慢轮询（idle 5s / running 1s）。
7. **Excel 非阻塞**：导出移至 Web Worker，主线程不冻结。
8. **i18n 框架**：引入 vue-i18n，提取全部中文文案。

## 三、非目标

- 不做端到端（E2E）测试（Playwright/Cypress），仅单元 + 组件测试。
- 不做完整的组件测试覆盖，仅覆盖纯展示组件（StatusBadge 等）。
- 不为所有页面写组件测试，仅纯函数模块。
- 不重构现有组件结构（布局/样式/状态管理保持不变）。
- 不引入 TypeScript strict 以外的类型规则变更。
- 后端 SSE 仅推队列状态变更，不推日志流/下载进度等其他事件（留后续迭代）。
- i18n 本批次仅完成框架搭建 + 中文 key 提取 + 英文翻译，不追求全部语言。

---

## 四、关键设计决策（用户已确认）

| 维度 | 决策 | 说明 |
|---|---|---|
| #17 API 层 | **按模块封装强类型函数** | 新建 `src/api/` 目录，按后端模块拆分（tasks.ts/queue.ts/benchmarks.ts 等），每端点封装为强类型函数。74 处内联调用全部替换。 |
| #22 SSE | **本批次完整实现** | 后端新建 `/events` SSE 端点 + scheduler 事件总线，前端 TasksPage/BenchmarkPage 改用 EventSource。#10 慢轮询作为 SSE 断线降级方案。 |
| #22 SSE 认证 | **query 参数传 token** | EventSource 不支持自定义 header，通过 `/events?token=xxx` 传 token，后端新建 `verify_auth_query` 依赖验证。单用户本地工具可接受 token 入 URL。 |
| #20 测试 | **Vitest + ESLint，覆盖纯函数** | Vitest + @vue/test-utils + ESLint flat config。优先覆盖 metricsStats/chartAxis/excelExporter/utils 纯函数。组件测试仅覆盖 StatusBadge 等纯展示组件。 |

---

## 五、模块 A：前端 API 抽象层（#17）

### 5.1 目录结构

```
frontend/src/api/
├── index.ts          # re-export 所有模块 + 通用 request()
├── client.ts         # 底层 fetch 封装（api.ts 的核心逻辑迁移至此）
├── benchmarks.ts     # /benchmarks 端点
├── queue.ts          # /queue 端点
├── tasks.ts          # /tasks 端点
├── profiles.ts       # /profiles 端点
├── models.ts         # /models + /models/downloads 端点
├── services.ts       # /services 端点
├── settings.ts       # /settings 端点
├── arguments.ts      # /arguments 端点
└── types.ts          # 公共响应类型（如 PaginatedResponse<T>）
```

### 5.2 底层 client.ts

将现有 `api.ts` 的核心逻辑（fetch + 错误处理 + jsonBody）迁移到 `client.ts`，暴露：
```ts
export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  params?: Record<string, string | number | boolean>  // GET 查询参数，序列化为 query string
  signal?: AbortSignal       // 支持取消
}
export async function request<T>(path: string, opts?: RequestOptions): Promise<T>
```
- 保留现有的 `API_BASE` 前缀（`import.meta.env.VITE_API_BASE || '/api/v1'`）、`getAuthToken()` + `Authorization: Bearer` header、401 跳转登录逻辑。
- 新增 `signal` 参数透传给 `fetch`，支持 AbortController 取消。
- 保留现有 `store.notify('error', ...)` 错误通知行为。
- GET 请求的查询参数通过 `params?: Record<string, string | number>` 选项序列化为 query string（拼到 URL 上），不通过 `body` 传递。

### 5.3 模块封装示例

`api/queue.ts`：
```ts
import { request } from './client'
import type { TaskQueueState } from '@/types'

export const queueApi = {
  get: (signal?: AbortSignal) => request<TaskQueueState>('/queue', { signal }),
  start: () => request<TaskQueueState>('/queue', { method: 'PATCH', body: { status: 'start' } }),
  pause: () => request<TaskQueueState>('/queue', { method: 'PATCH', body: { status: 'pause' } }),
  resume: () => request<TaskQueueState>('/queue', { method: 'PATCH', body: { status: 'resume' } }),
  stop: () => request<TaskQueueState>('/queue', { method: 'PATCH', body: { status: 'stop' } }),
  clear: () => request<TaskQueueState>('/queue', { method: 'PATCH', body: { status: 'clear' } }),
}
```

`api/tasks.ts`：
```ts
import { request } from './client'
import type { BenchmarkTask, PaginatedResponse } from '@/types'

export const tasksApi = {
  list: (params?: { offset?: number; limit?: number }, signal?: AbortSignal) =>
    request<PaginatedResponse<BenchmarkTask>>('/tasks', { params, signal }),  // params 序列化为 ?offset=&limit=
  get: (id: string) => request<BenchmarkTask>(`/tasks/${id}`),
  create: (data: unknown) => request<BenchmarkTask>('/tasks', { method: 'POST', body: data }),
  update: (id: string, data: unknown) => request<BenchmarkTask>(`/tasks/${id}`, { method: 'PUT', body: data }),
  delete: (id: string) => request<{ deleted: boolean }>(`/tasks/${id}`, { method: 'DELETE' }),
}
```

### 5.4 分页响应类型

`api/types.ts` 定义统一分页包裹类型（批次 3 引入的结构）：
```ts
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  offset: number
  limit: number
}
```
所有列表接口（benchmarks/profiles/models/downloads/tasks）返回 `PaginatedResponse<T>`。

### 5.5 调用方改造

10 个 `.vue` 页面的 74 处内联 `api(...)` 调用全部替换为模块函数调用。例如 TasksPage.vue：
```ts
// 改造前
const data = await api<TaskQueueState>('/queue')
// 改造后
const data = await queueApi.get()
```

### 5.6 向后兼容

- 保留 `src/api.ts` 作为 re-export 入口（`export * from './api'`），避免破坏可能的第三方引用。
- `jsonBody` helper 内联进 client.ts 的 `request`，不再需要调用方手动 `...jsonBody(...)`。

---

## 六、模块 B：深拷贝工具（#18）

### 6.1 实现

`utils.ts` 新增：
```ts
export function cloneConfig<T>(obj: T): T {
  if (typeof structuredClone === 'function') return structuredClone(obj)
  return JSON.parse(JSON.stringify(obj))  // 兜底（老旧浏览器）
}
```
- 优先用浏览器原生 `structuredClone`（支持 Date/Map/Set/循环引用/undefined，Chromium 98+ 支持）。
- 兜底用 JSON hack（Electron 内嵌 Chromium 版本足够新，兜底极少触发）。

### 6.2 替换点

- `ProfilesPage.vue`：`edit()` 中 `JSON.parse(JSON.stringify(profile))` → `cloneConfig(profile)`
- `ServicesPage.vue`：同样替换

---

## 七、模块 C：操作 busy 防重（#19）

### 7.1 组合式函数 useBusy

新建 `src/composables/useBusy.ts`：
```ts
import { ref, type Ref } from 'vue'

export function useBusy() {
  const busy = ref<Record<string, boolean>>({})

  async function run<T>(key: string, fn: () => Promise<T>): Promise<T | undefined> {
    if (busy.value[key]) return undefined
    busy.value[key] = true
    try {
      return await fn()
    } finally {
      busy.value[key] = false
    }
  }

  function isBusy(key: string): boolean {
    return !!busy.value[key]
  }

  return { busy, run, isBusy }
}
```

### 7.2 应用范围

| 页面 | 操作 key | 现状 |
|---|---|---|
| TasksPage | `queue.start`/`queue.pause`/`queue.stop`/`queue.clear`/`item.delete`/`item.reorder` | 仅一个全局 `acting`，无区分 |
| ProfilesPage | `profile.create`/`profile.update`/`profile.delete` | 无 busy |
| ServicesPage | `service.create`/`service.update`/`service.delete`/`service.deploy`/`service.start`/`service.stop` | 无 busy |
| BenchmarkPage | `benchmark.start`/`benchmark.cancel` | 无 busy |
| ObservationPage | `export.excel` | 有 `exporting` ref 但按钮未绑 disabled |

### 7.3 模板绑定

按钮 `:disabled="isBusy('xxx')"` 绑定，防止重复点击。`run()` 返回 `undefined` 时调用方静默跳过（不报错）。

### 7.4 与现有 acting 的关系

TasksPage 现有 `acting` ref 统一替换为 `useBusy()`。其余页面新增 `useBusy()`。

---

## 八、模块 D：前端测试 + ESLint（#20）

### 8.1 Vitest 配置

新增 `vitest.config.ts`：
```ts
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  test: {
    environment: 'jsdom',
    globals: true,
    coverage: { provider: 'v8', include: ['src/utils.ts', 'src/metricsStats.ts', 'src/**/chartAxis.ts', 'src/excelExporter.ts'] },
  },
})
```

### 8.2 测试文件

```
frontend/src/__tests__/
├── metricsStats.test.ts    # 统计聚合：空数据/单点/分位数/异常值
├── chartAxis.test.ts       # 轴布局：niceNumber/范围/刻度生成
├── excelExporter.test.ts   # Excel 生成：mock ExcelJS，断言 sheet 结构
├── utils.test.ts           # cloneConfig/formatDate/formatDuration
└── components/
    └── StatusBadge.test.ts # 纯展示组件：props → 渲染
```

### 8.3 测试内容

- `metricsStats.test.ts`：`aggregateMetrics([])` 空数据、单点数据、多 attempt 聚合、分位数边界（p50/p95/p99）、异常值剔除。
- `chartAxis.test.ts`：`niceNumber()` 取整逻辑、轴范围计算（min/max/nice step）、刻度数组生成。
- `excelExporter.test.ts`：mock `ExcelJS.Workbook`，断言 `addSheet`/`addRow` 调用次数与参数、文件名生成。
- `utils.test.ts`：`cloneConfig` 深拷贝（嵌套对象/数组/Date）、`formatDate` 各时区、`formatDuration` 边界。
- `StatusBadge.test.ts`：mount + props.status → 文本/颜色 class。

### 8.4 ESLint

新增 `eslint.config.js`（flat config）：
```js
import js from '@eslint/js'
import ts from 'typescript-eslint'
import vue from 'eslint-plugin-vue'

export default [
  js.configs.recommended,
  ...ts.configs.recommended,
  ...vue.configs['flat/recommended'],
  { rules: { 'vue/multi-word-component-names': 'off', '@typescript-eslint/no-unused-vars': 'warn' } },
]
```

`package.json` 新增脚本：
```json
{
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "eslint src --ext .ts,.vue",
    "lint:fix": "eslint src --ext .ts,.vue --fix"
  }
}
```

### 8.5 依赖

```
devDependencies:
  vitest @vue/test-utils jsdom @eslint/js typescript-eslint eslint-plugin-vue
```

---

## 九、模块 E：SSE 实时推送（#22）—— 跨前后端

### 9.1 后端事件总线

在 `QueueScheduler`（`backend/app/services/task_queue.py`）增加订阅机制：

```python
class QueueScheduler:
    def __init__(self) -> None:
        ...
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=16)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _publish(self) -> None:
        """向所有订阅者投递一个事件标记（非阻塞）。"""
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass  # 慢消费者丢弃事件，下次会收到最新快照
```

修改 `notify()`：在 `notify_all()` 后调用 `self._publish()`：
```python
def notify(self) -> None:
    with self._condition:
        self._condition.notify_all()
    self._publish()
```

### 9.2 后端 SSE 认证（query token）

现有认证是 Bearer token（`Authorization` header），但 `EventSource` 不支持自定义 header。采用 **query 参数传 token** 方案：

`backend/app/api/auth.py` 新增 `verify_auth_query` 依赖：
```python
from fastapi import Query
from app.services.auth_service import verify_token

def verify_auth_query(token: str = Query(..., min_length=1), db: Session = Depends(get_db)) -> None:
    if not verify_token(db, token):
        raise HTTPException(status_code=401, detail="invalid token")
```

> events router 不用全局 `Depends(verify_auth)`（main.py L116 给所有 router 注册的），而是用自己的 `verify_auth_query`。

### 9.3 后端 SSE 端点

新建 `backend/app/api/events.py`：

```python
import asyncio
import functools
import json
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.api.auth import verify_auth_query
from app.services.task_queue import get_scheduler, serialize_queue, _ensure_queue_row

router = APIRouter(prefix="/events", tags=["events"], dependencies=[Depends(verify_auth_query)])

@router.get("")
async def queue_events(db: Session = Depends(get_db)):
    scheduler = get_scheduler()
    q = scheduler.subscribe()

    async def event_stream():
        try:
            q_row = _ensure_queue_row(db)
            # 首次立即推送当前状态
            yield _format_sse(serialize_queue(db, q_row))
            while True:
                # 用 run_in_executor 在线程池等待队列事件，避免阻塞事件循环
                # 注意：queue.Queue.get(block, timeout) 的第一个位置参数是 block，必须用 partial 传 timeout 关键字
                loop = asyncio.get_event_loop()
                try:
                    await loop.run_in_executor(None, functools.partial(q.get, timeout=5))
                except Exception:
                    pass  # 超时或队列为空，继续推送当前状态（保活）
                yield _format_sse(serialize_queue(db, q_row))
        finally:
            scheduler.unsubscribe(q)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

def _format_sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
```

关键设计：
- **跨线程桥接**：scheduler 线程通过 `queue.Queue` 投递事件，SSE 端点用 `run_in_executor` 等待，不阻塞 FastAPI 事件循环。`functools.partial(q.get, timeout=5)` 确保 timeout 作为关键字参数传递（`q.get` 第一位置参数是 `block`）。
- **首次立即推送**：客户端连接时立即收到当前状态，无需等待第一次变更。
- **5s 保活超时**：`q.get(timeout=5)` 超时后仍 yield 一次（重发当前状态），既是 keepalive 又保证客户端与服务端状态同步。
- **慢消费者丢弃**：`put_nowait` 队列满时丢弃事件（maxsize=16），客户端下次收到的是最新快照，无累积问题。
- **序列化复用**：`serialize_queue` 复用批次 3 优化的批量加载逻辑（常数查询），`_ensure_queue_row(db)` 获取/创建队列行。
- **X-Accel-Buffering: no**：禁用 Nginx 反代缓冲（如有），保证 SSE 实时推送。
- **每客户端独立 db session**：`Depends(get_db)` 在请求开始时创建，SSE 流结束时关闭。长连接期间该 session 保持打开，SQLite 单写者锁不影响（SSE 只读）。
- **认证**：`verify_auth_query` 从 query 参数取 token 验证，events router 单独依赖它。

> **注意**：`get_db` yield 依赖在 StreamingResponse 中的生命周期——FastAPI 在 `event_stream()` 生成器结束后才执行 `db.close()`。长连接期间该 session 保持打开，SQLite 单写者锁不影响（SSE 只读）。

### 9.4 前端 EventSource 订阅

新建 `src/composables/useQueueStream.ts`：
```ts
import { ref, onUnmounted, type Ref } from 'vue'
import type { TaskQueueState } from '@/types'
import { getAuthToken } from '@/api'

export function useQueueStream(): { state: Ref<TaskQueueState | null>; connected: Ref<boolean> } {
  const state = ref<TaskQueueState | null>(null)
  const connected = ref(false)
  let es: EventSource | null = null

  function connect() {
    const token = getAuthToken() || ''
    // EventSource 不支持自定义 header，通过 query 参数传 token（后端 verify_auth_query 验证）
    es = new EventSource(`/api/v1/events?token=${encodeURIComponent(token)}`)
    es.onopen = () => { connected.value = true }
    es.onmessage = (ev) => { state.value = JSON.parse(ev.data) }
    es.onerror = () => {
      connected.value = false
      es?.close()
      // 降级到慢轮询（模块 F）
      setTimeout(connect, 3000)  // 3s 后重连
    }
  }
  connect()

  onUnmounted(() => es?.close())
  return { state, connected }
}
```

### 9.5 应用点

- `TasksPage.vue`：移除 `setInterval(loadQueue, 1000)`，改用 `useQueueStream()`。队列状态实时更新。
- `BenchmarkPage.vue`：移除 `setInterval(checkActive, 1000)`，改用 SSE（job 状态变更通过队列事件感知）。
- `ModelsPage.vue` 下载进度轮询：本批次**不改**（下载进度是高频小数据，SSE 推送队列状态已够；下载进度保持 2.2s 轮询，留后续迭代）。

### 9.6 后端依赖

`backend/app/main.py` 注册 events router：
```python
from app.api import events
app.include_router(events.router, prefix="/api/v1")
```

> 注意：events router 自带 `verify_auth_query` 依赖，不要重复加 `Depends(verify_auth)`。

### 9.7 SSE 事件格式

```
data: {"queue":{"status":"running","session_id":"...","items":[...],"session_stats":{...}}}
```
单字段 `data`，JSON 字符串，UTF-8（`ensure_ascii=False`）。不使用 `event:` / `id:` 字段（本批次仅需"状态快照"单一事件类型）。

---

## 十、模块 F：慢轮询降级（#10）

### 10.1 定位

SSE 是主通道；#10 慢轮询作为 **SSE 断线时的降级方案**，而非独立功能。

### 10.2 实现

`useQueueStream.ts` 的 `onerror` 分支（见 9.3）：SSE 断线时 `connected.value = false`，启动慢轮询兜底：
```ts
let pollTimer: number | null = null

function startFallbackPolling() {
  pollTimer = window.setInterval(async () => {
    state.value = await queueApi.get()
  }, 5000)  // idle 5s
}

function stopFallbackPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

// onerror:
connected.value = false
es?.close()
startFallbackPolling()
setTimeout(connect, 3000)  // 同时尝试重连 SSE

// onopen (重连成功):
connected.value = true
stopFallbackPolling()
```

### 10.3 运行时行为

- SSE 正常：实时推送，无轮询。
- SSE 断线：5s 慢轮询兜底 + 3s 后自动重连 SSE。
- 重连成功：停止慢轮询，恢复 SSE。

> 不再需要独立的"#10 idle 慢轮询"逻辑——SSE 断线时统一 5s 轮询，无论队列是否 idle（断线时无法感知队列状态，必须轮询）。

---

## 十一、模块 G：Excel 导出 Web Worker（#16）

### 11.1 Worker 文件

新建 `src/workers/excelExport.worker.ts`：
```ts
import { buildWorkbookBlob } from '@/excelExporter'

self.onmessage = async (e: MessageEvent) => {
  const { jobs, attempts, fileName } = e.data
  try {
    const blob = await buildWorkbookBlob(jobs, attempts, fileName)  // 返回 Blob
    self.postMessage({ ok: true, blob })
  } catch (err) {
    self.postMessage({ ok: false, error: String(err) })
  }
}
```

### 11.2 excelExporter 改造

`excelExporter.ts` 的 `exportObservationExcel` 拆为两步：
1. `buildWorkbookBlob(jobs, attempts, fileName)`：纯计算，返回 `Blob`（可在 Worker 调用）。
2. `downloadBlob(blob, fileName)`：触发浏览器下载（仅主线程可调，Worker 无 DOM）。

### 11.3 调用方改造

`ObservationPage.vue` 的 `exportExcel()` 改为：
```ts
const worker = new Worker(new URL('./workers/excelExport.worker.ts', import.meta.url), { type: 'module' })
worker.onmessage = (e) => {
  if (e.data.ok) downloadBlob(e.data.blob, fileName)
  else store.notify('error', e.data.error)
  worker.terminate()
  exporting.value = false
}
worker.postMessage({ jobs: selectedJobs, attempts: allAttempts, fileName })
```

### 11.4 Vite 配置

Vite 原生支持 `new Worker(new URL(...))` 语法，无需额外配置。Worker 代码单独打包。

### 11.5 数据序列化

jobs/attempts 通过 `postMessage` 传递（结构化克隆算法），无需 JSON 序列化。数据量较大时（数百 job）仍可接受（结构化克隆比 JSON 快）。

---

## 十二、模块 H：国际化 i18n（#21）

### 12.1 依赖

```
dependencies:
  vue-i18n@10
```

### 12.2 配置

新建 `src/i18n/index.ts`：
```ts
import { createI18n } from 'vue-i18n'
import zh from './locales/zh.json'
import en from './locales/en.json'

export const i18n = createI18n({
  legacy: false,
  locale: localStorage.getItem('locale') || 'zh',
  fallbackLocale: 'zh',
  messages: { zh, en },
})
```

`main.ts` 注册：`app.use(i18n)`。

### 12.3 语言文件

```
src/i18n/locales/
├── zh.json    # 从各 .vue 提取的中文文案
└── en.json    # 英文翻译
```

按页面/模块组织 key：
```json
{
  "common": { "save": "保存", "cancel": "取消", "delete": "删除", "loading": "加载中..." },
  "tasks": { "title": "任务队列", "start": "开始", "pause": "暂停", "empty": "暂无任务" },
  "profiles": { "title": "推理配置", "new": "新建配置" },
  ...
}
```

### 12.4 使用

模板中 `t('tasks.title')` 替换硬编码中文。组合式 API：`const { t } = useI18n()`。

### 12.5 语言切换

设置页或顶部栏增加语言切换下拉，切换时 `localStorage.setItem('locale', lang)` + `i18n.global.locale.value = lang`。

### 12.6 范围

本批次完成框架搭建 + 全部现有文案提取 + 中英文翻译。新增功能文案随开发同步补充。

---

## 十三、配置变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| 前端无新增环境变量 | — | SSE 端点路径硬编码 `/api/v1/events` |
| `LLAMALENS_SSE_KEEPALIVE_S` | `5` | SSE 队列等待超时（保活间隔），后端 |
| `LLAMALENS_SSE_QUEUE_MAXSIZE` | `16` | 每订阅者事件队列上限，后端 |
| `LLAMALENS_SSE_RECONNECT_MS` | `3000` | SSE 断线重连间隔，前端 |
| `LLAMALENS_FALLBACK_POLL_MS` | `5000` | SSE 断线时慢轮询间隔，前端 |

前端配置通过 `src/config.ts` 统一管理（读 `import.meta.env`）。

---

## 十四、安全考量

1. **SSE 连接数限制**：每个浏览器标签页一个 SSE 连接。无服务端连接数上限（单用户场景可接受；多用户场景需加限制，本批次不做）。
2. **SSE 与认证**：`EventSource` 不支持自定义 header，通过 query 参数传 token（`/events?token=xxx`），后端 `verify_auth_query` 验证。token 会出现在 URL/访问日志中，但本项目是单用户本地工具，风险可接受。如需更高安全性可改用 fetch + ReadableStream 方案（本批次不做）。
3. **db session 生命周期**：SSE 长连接持有 db session 只读，不参与写事务，不影响 SQLite 单写者锁。
4. **Web Worker 数据**：jobs/attempts 通过 postMessage 传递，不经过网络，无泄露风险。
5. **i18n 无注入风险**：vue-i18n 的 `t()` 是纯字符串拼接，无 eval。
6. **AbortController**：API 层的 `signal` 参数允许组件卸载时取消进行中的请求，避免内存泄漏与对已卸载组件的状态更新。

---

## 十五、文件改动清单

### 后端新增
- `backend/app/api/events.py`（SSE 端点）

### 后端修改
- `backend/app/services/task_queue.py`（QueueScheduler 增加订阅/发布）
- `backend/app/api/auth.py`（新增 `verify_auth_query` 依赖）
- `backend/app/main.py`（注册 events router）

### 前端新增
- `frontend/src/api/`（client.ts + 8 个模块文件 + types.ts + index.ts）
- `frontend/src/composables/useBusy.ts`
- `frontend/src/composables/useQueueStream.ts`
- `frontend/src/workers/excelExport.worker.ts`
- `frontend/src/i18n/index.ts`
- `frontend/src/i18n/locales/zh.json`
- `frontend/src/i18n/locales/en.json`
- `frontend/src/config.ts`
- `frontend/src/__tests__/`（5 个测试文件）
- `frontend/vitest.config.ts`
- `frontend/eslint.config.js`

### 前端修改
- `frontend/src/api.ts`（改为 re-export 入口）
- `frontend/src/utils.ts`（新增 cloneConfig）
- `frontend/src/excelExporter.ts`（拆分 buildWorkbookBlob + downloadBlob）
- `frontend/src/main.ts`（注册 i18n）
- `frontend/package.json`（新增依赖 + 脚本）
- `frontend/tsconfig.json`（如需调整 test 路径）
- 10 个 `.vue` 页面（替换 74 处 api 调用 + busy + i18n）
  - `views/TasksPage.vue`（SSE 替代轮询 + busy + API 层 + i18n）
  - `views/BenchmarkPage.vue`（SSE 替代轮询 + busy + API 层 + i18n）
  - `views/ResultsPage.vue`（API 层 + i18n）
  - `views/ProfilesPage.vue`（cloneConfig + busy + API 层 + i18n）
  - `views/ModelsPage.vue`（API 层 + i18n）
  - `views/ServicesPage.vue`（cloneConfig + busy + API 层 + i18n）
  - `views/ObservationPage.vue`（Excel Worker + API 层 + i18n）
  - `views/DashboardPage.vue`（API 层 + i18n）
  - `views/SettingsPage.vue`（i18n + 语言切换）
  - `views/LoginPage.vue`（API 层 + i18n）

---

## 十六、依赖变更

### 前端 dependencies 新增
- `vue-i18n@^10` —— i18n 框架

### 前端 devDependencies 新增
- `vitest` —— 测试框架
- `@vue/test-utils` —— Vue 组件测试工具
- `jsdom` —— 测试 DOM 环境
- `@eslint/js` —— ESLint 推荐规则
- `typescript-eslint` —— TypeScript ESLint 解析器 + 规则
- `eslint-plugin-vue` —— Vue ESLint 规则

### 后端无新增依赖
（`StreamingResponse` 是 FastAPI 内置，`queue.Queue`/`threading` 是标准库）

---

## 十七、验证计划

### 17.1 前端单元测试
```bash
cd frontend && npm run test
```
预期：metricsStats/chartAxis/excelExporter/utils/StatusBadge 测试全部通过。

### 17.2 ESLint
```bash
cd frontend && npm run lint
```
预期：无 error（warn 可接受）。

### 17.3 前端构建
```bash
cd frontend && npm run build
```
预期：vue-tsc 类型检查通过，vite 打包成功（含 Worker 单独 chunk）。

### 17.4 后端测试
```bash
cd backend && python -m pytest -q
```
预期：现有 67 passed + 新增 events API 测试（SSE 端点订阅/退订/推送）通过。

### 17.5 手动验证
- TasksPage 队列状态实时更新（启动/暂停/完成时无延迟）。
- SSE 断线（手动关闭后端）→ 慢轮询兜底 → 后端恢复 → 自动重连 SSE。
- Excel 导出大数据集时 UI 不冻结，进度条正常。
- 语言切换中/英文即时生效。
- 按钮防重：连续点击只触发一次请求。

---

## 十八、实施顺序

1. **模块 A（#17 API 层）** 先做——后续所有模块都依赖 API 层的强类型函数。
2. **模块 B（#18 cloneConfig）** 独立小改，可并行。
3. **模块 C（#19 useBusy）** 依赖 API 层（busy 包裹 API 调用）。
4. **模块 D（#20 Vitest + ESLint）** 尽早做——为后续模块提供测试保障。可与 A/B/C 并行。
5. **模块 E（#22 SSE 后端 + 前端）** 后端事件总线 + 端点 + 前端 EventSource。工作量最大。
6. **模块 F（#10 慢轮询降级）** 在 E 完成后做（依赖 SSE 的 onerror 分支）。
7. **模块 G（#16 Excel Worker）** 独立，可并行。
8. **模块 H（#21 i18n）** 最后做——文案提取需等前面模块稳定，避免频繁改 key。

> 建议并行：A+B+D 先行，C 跟随 A，E/G 独立推进，F 收尾，H 最后。

---

## 十九、范围边界（本批次不做）

- 不做 E2E 测试（Playwright/Cypress）。
- 不做完整组件测试覆盖（仅纯函数 + StatusBadge）。
- 不改 ModelsPage 下载进度轮询（保持 2.2s，留后续）。
- 后端 SSE 仅推队列状态，不推日志/下载进度/任务输出流。
- 不做 SSE 连接数限制（单用户场景）。
- i18n 仅中英文，不接入其他语言。
- 不重构组件结构与状态管理（Pinia store 保持不变）。
- 不引入 TypeScript strict 以外的类型规则。
- #3/ #11/ #12/ #17 后端部分、#23/ #24 留批次 5。
