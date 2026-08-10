# 观测页（Observation Page）实施计划

## 背景与目标

当前结果页 `ResultsPage.vue` 同时承担了「结果列表对比 / 趋势图 / 测试详情 / 轮次明细 / 删除导出」等多重职责。用户希望把其中的「趋势图」**移动抽离**出来，做成一个**专注观测**的独立页面，支持选择结果、切换图表、导出图表、调整结果顺序，并补充更多观测向功能。移动后结果页不再保留趋势图区块。

技术栈：Vue 3 `<script setup>` + TS + ECharts 6 + vue-router + Pinia + @tabler/icons-vue。所有数据来自现有 API：`GET /benchmarks`（列表）、`GET /benchmarks/{id}`（含 attempts 详情）、`GET /benchmarks?task_id=`（按任务筛选）。后端无需改动。

**新增依赖**：`exceljs`（浏览器端生成 .xlsx，支持把图表 PNG 嵌入工作表 + 写入结构化数据表）。安装：`npm i exceljs`。

***

## 总体设计

新建页面 `ObservationPage.vue`，路由 `/observation`，导航标签「观测」。页面分为三块：

1. **数据源面板（左侧/顶部）**：结果多选 + 搜索/状态/任务过滤 + 拖拽排序。
2. **图表观测区（主体）**：多个可配置的图表卡片（趋势线图 / 对比柱状图 / 分位区间图 / 统计表格），每个卡片可独立切换指标、统计量、导出。
3. **观测控制条**：统一指标切换、统计量切换（均值/中位数/p10/p90/min/max）、Excel 导出、单图 PNG 导出。

### 数据流

* 复用 `api.ts` 的 `api<T>()` 与现有 `BenchmarkJob` / `MetricSummary` 类型。

* 排序后的 job 列表作为各图表的统一输入（顺序即 x 轴/分组顺序）。

* **分位兜底（自动懒加载补全）**：列表接口 `GET /benchmarks` 的 summary 仅保证 `average`，`median/p10/p90/min/max` 依赖运行时写入，历史 job 可能缺失。对选中且 succeeded 的 job，先检查其 summary 是否含完整分位；缺失则懒加载 `GET /benchmarks/{id}` 拿到 attempts，由前端用 attempts 的原始指标值自行计算 `median/p10/p90/min/max`（`ttft_ms / prefill_tps / decode_tps / client_decode_tps / total_ms` 五项）。结果缓存到 `detailCache` 避免重复请求。这样分位图/统计表数据完整，且只对缺失项多发请求。

***

## 实施步骤

### 1. 注册路由与导航入口

**文件：** `frontend/src/router.ts`

* 新增路由：`{ path: '/observation', component: () => import('./views/ObservationPage.vue'), meta: { title: '观测' } }`

**文件：** `frontend/src/App.vue`

* 在 `nav` 数组中新增：`{ to: '/observation', label: '观测', icon: IconChartLine }`（从 `@tabler/icons-vue` 导入 `IconChartLine`），放在「结果」之后、「设置」之前。

### 2. 抽离可复用图表组件

把 `MetricsChart.vue` 的能力拆成更通用的组件，放到 `frontend/src/components/charts/`。原 `MetricsChart.vue` 仅被结果页趋势图使用，移动后结果页不再有趋势图区块，`MetricsChart.vue` 成为无引用文件，**删除**（避免死代码）。

> 原则：新页面不复用 `MetricsChart.vue`（它写死 TTFT/Prefill/Decode 三条线），而是新建参数化组件。

#### 2.1 `TrendLineChart.vue`（趋势线图）

* Props：`jobs: BenchmarkJob[]`、`metrics: MetricConfig[]`（指标 key + 显示名 + 单位 + 轴方向 left/right）、`statistic: 'average' | 'median' | 'p10' | 'p90' | 'min' | 'max'`、`smooth: boolean`。

* 基于现有 `MetricsChart.vue` 改造：x 轴 = `jobs` 顺序（由父组件排好序传入，不再内部 sort），多 yAxis 动态生成（按指标的 `axis` 分组去重），series 动态生成。

* 暴露 `getDataURL(opts)` 方法（`defineExpose`），内部调用 `chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: ... })`，供 Excel 导出与单图 PNG 导出共用。

#### 2.2 `ComparisonBarChart.vue`（对比柱状图）

* 引入 `BarChart`（`echarts/charts`）。

* Props 同上。每个 job 一组柱，每个指标一根柱；多指标时分组柱状，单指标时纯柱状。

* 同样 `defineExpose({ getDataURL })`。

#### 2.3 `PercentileRangeChart.vue`（分位区间图）

* 用 ECharts `custom` series 或 boxplot 展示每个 job 的 `p10 ~ p90` 区间 + `median` 中位线 + `min/max` 端点。

* 数据来源：优先取 `MetricSummary` 的 p10/p90/min/max/median；若该 job 的 summary 缺失分位，则用「分位兜底」加载的 attempts 前端计算结果（见数据流）。组件接收的是「已补全」的 job 数据，不关心来源。

* 适合「看离散度」，弥补趋势图只看均值的不足。

* 同样 `defineExpose({ getDataURL })`。

#### 2.4 `ChartCard.vue`（图表卡片容器）

* 复用 `PageSection` 风格但更轻：标题 + 描述 + actions 插槽（放单图「导出 PNG」按钮）+ body 插槽。

* 保持简洁，本次不做全屏/SVG/剪贴板（见「后续增强」）。

#### 2.5 `StatisticsTable.vue`（统计表格）

* 表格形式列出每个 job 的各指标各统计量（均值/中位数/p10/p90/min/max），可直接复用现有 `.data-table` 样式。

* 数据同样来自「已补全」的 job（分位缺失项用前端计算补齐）。

* 该表格的数据结构同时作为 Excel「汇总数据」工作表的来源（页内展示与导出共用一份计算函数）。

### 2.6 `metricsStats.ts`（统计计算工具）

* 纯函数模块，集中处理：从 `BenchmarkJob` 取某指标的某统计量（含分位兜底后的数据）；从 attempts 数组计算 median/p10/p90/min/max/average；选中集合的聚合（均值/最佳/最差）。

* 页面展示、统计表、Excel 导出共用，避免重复实现。

### 2.7 `excelExporter.ts`（Excel 导出工具）

用 `exceljs` 生成 `.xlsx`，**一个文件包含「数据 + 图」两部分**，结构如下：

* **工作表 1「汇总数据」**：与 `StatisticsTable.vue` 一致的表，结构化单元格而非图片。

  * 列：序号 / 测试名 / 目标(Service·alias) / 模型 / 状态 / 创建时间 / 成功数 / 失败数，随后是各指标 × 各统计量（如 `TTFT 均值`、`TTFT 中位数`、`TTFT p10`、`TTFT p90`、`Prefill 均值`…）。

  * 表头加粗 + 背景色，数字列设置数字格式（`0.00`），ms 类列追加单位说明。

  * 末尾追加一行「合计/平均」：对选中集合的各指标做均值（与页面顶部统计摘要面板一致）。

  * 行顺序严格遵循用户在页面里排好的 `selectedIds` 顺序。

* **工作表 2「图表」**：把启用的图表逐张作为 PNG 嵌入。

  * 通过各图表组件 `defineExpose` 暴露的 `getDataURL()` 拿到 base64 PNG → 解码为 ArrayBuffer → `workbook.addImage({ buffer, extension: 'png' })` → `worksheet.addImage(id, { tl, br })` 锚定到单元格区域，每张图占若干行，图上方写一行标题（图表类型 + 指标 + 统计量）。

  * 列宽与行高按图片比例调整，保证不变形。

* **工作表 3「轮次明细」（可选启用）**：当用户勾选「含轮次明细」时，对选中 job 懒加载 `GET /benchmarks/{id}`，把每个正式成功 attempt 展平成行：测试名 / ordinal / measurement\_mode / TTFT / Prefill / Decode / Client Decode / Total / prompt\_tokens / predicted\_tokens / 状态。便于在 Excel 里二次透视分析。

* 导出文件名：`llamalens-observation-YYYY-MM-DD-HHmm.xlsx`。

* 文件生成后用 `workbook.xlsx.writeBuffer()` → `Blob` → 触发下载（与现有 CSV 导出同模式）。

> ExcelJS 在浏览器端通过 `import ExcelJS from 'exceljs'`（或 `exceljs/dist/exceljs.min.js`）即可使用；Vite 会按 ESM 处理。需确认 `tsconfig` 的 `moduleResolution` 能解析其类型（其自带 `.d.ts`）。

### 3. 新建观测页 `frontend/src/views/ObservationPage.vue`

#### 3.1 状态

* `jobs: BenchmarkJob[]`（全部列表，`onMounted` 调 `GET /benchmarks`）

* `selectedIds: string[]`（选中的 job id，顺序即展示顺序，支持拖拽排序）

* `query` / `status` / `taskFilterId`（过滤，复用结果页交互模式）

* `detailCache: Record<string, BenchmarkJob>`（懒加载的含 attempts 详情，供分位兜底计算用）

* `enrichedJobs`（computed）：把 `selectedIds` 对应的 succeeded job，叠加分位兜底结果，作为图表与统计表的统一输入

* 全局 `metricKeys`（默认勾选 ttft\_ms / prefill\_tps / decode\_tps）

* 全局 `statistic`（默认 average）

* `chartLayout`：当前启用的图表卡片列表（趋势/柱状/分位/表格，可单独开关）

#### 3.2 数据源面板

* 顶部工具条：搜索框、状态筛选、任务筛选 chip（支持 `?task_id=` 进入）、刷新。

* 结果多选表/列表：复用 `.data-table` 样式，列：勾选框 / 测试名 / 目标 / 创建时间 / 状态。点击行选中，与「结果页」一致交互。

* **排序控制（拖拽 + 快捷排序）**：选中结果区使用 HTML5 原生拖拽列表，实时改变 `selectedIds` 顺序，图表立即重排。同时提供快捷排序按钮：「按时间升/降序」「按名称」「按 TTFT」「按 Prefill」「按 Decode」一键排序。拖拽为主、快捷为辅。

* 仅 `succeeded` 状态的 job 才进入图表（与现有趋势图逻辑一致）。

#### 3.3 图表观测区

* 用 `ChartCard` 包裹多个图表组件，网格布局（`.dashboard-columns` 类似两列或自适应）。

* 每张图共用全局 `metricKeys` / `statistic`，但可在卡片 actions 内独立覆盖（局部覆盖优先于全局）。

* 图表输入 = `enrichedJobs`（按 `selectedIds` 顺序过滤 + 排序后的 succeeded job，叠加分位兜底结果）。

#### 3.4 观测控制条

* 指标多选 chips：TTFT / Prefill / Decode / Client Decode / Total / Prompt tokens / Predicted tokens。

* 统计量单选：均值 / 中位数 / p10 / p90 / min / max。

* 平滑曲线开关、显示数据标签开关、图例位置。

* **导出按钮**（主操作）：

  * 「导出 Excel」：调用 `excelExporter`，生成包含「汇总数据 + 图表 + 可选轮次明细」三个工作表的 `.xlsx`。提供「含轮次明细」复选框，勾选后才懒加载 attempts 并写入工作表 3。

  * 「导出当前图 PNG」：每张图表卡片内独立按钮，快速导出单张图（`chart.getDataURL` 直接触发下载），便于贴文档。

* Excel 导出会带上当前页面的「指标/统计量/排序」配置，所见即所得。

### 4. 功能范围

**本次实现（MVP + 统计摘要 + 分位图）：**

1. **结果多选 + 拖拽排序 + 快捷排序**：数据源面板勾选 job，拖拽改顺序，快捷按钮一键排序（见 3.2）。
2. **趋势线图**（`TrendLineChart`）：多指标可切换、多统计量可切换、智能多轴（ms 类共用右轴、tok/s 类共用左轴、tokens 类单独轴，按指标 `axis` 自动分组）。
3. **对比柱状图**（`ComparisonBarChart`）：多指标分组柱对比。
4. **分位区间图**（`PercentileRangeChart`）：p10\~p90 区间 + 中位线 + min/max，看离散度。
5. **统计表格**（`StatisticsTable`）：各指标各统计量，含分位兜底补齐数据。
6. **统计摘要面板**：顶部一行 `MetricBlock`，展示选中集合的聚合（TTFT 均值、Decode 均值、最佳/最差值）。
7. **指标/统计量全局切换**：控制条 chips 与单选，驱动所有图表同步。
8. **异常高亮**：对 p90/p10 离散度过大或成功率低于阈值的 job，在统计表/图表 tooltip 中标识提示。
9. **Excel 导出**（`excelExporter`）：汇总数据 + 图表 PNG + 可选轮次明细三工作表 .xlsx。
10. **单图 PNG 导出**：每张图表卡片独立按钮快速导出。
11. **空选提示与引导**：未选时显示空状态并给出「跳转结果页」入口。

**后续增强（本次不做，预留扩展点）：**

* 基线对比模式（相对 baseline 百分比/差值）。

* 按维度分组着色（模型/service/task 分面）。

* 视图预设（localStorage 保存指标+统计量+排序+卡片开关，URL 同步分享）。

* 图表全屏 modal。

* 自动刷新（轮询 `/benchmarks`）。

* SVG 导出（需注册 `SVGRenderer`）。

> 本次实现完成后，以上增强可在不改动主架构的前提下增量加入。

### 5. 样式

* 复用 `styles.css` 现有类：`.page-stack`、`.inline-actions`、`.compact-select`、`.search-box`、`.data-table-wrap`、`.metrics-row`、`.metric-block`、`.empty-state`、`.skeleton-stack`。

* 新增少量样式：拖拽列表项的 `drag-handle` / `dragging` 态、图表卡片 grid、异常高亮样式；统一加在 `styles.css` 末尾，遵循现有 CSS 变量（`--accent`、`--surface`、`--line` 等）。

### 6. 验证

* `cd frontend && npm install exceljs` 安装新依赖。

* `cd frontend && npm run build`（`vue-tsc -b && vite build`）确保类型与构建通过。

* 手动验证：

  * 进入 `/observation`，勾选若干成功 job，趋势图按选中顺序展示。

  * 拖拽改变顺序，图表即时重排；快捷排序按钮（按 TTFT/Decode 等）生效。

  * 切换指标/统计量，各图表同步更新。

  * 「导出 Excel」：打开生成的 .xlsx，确认工作表 1 有完整数据表（含合计行）、工作表 2 有嵌入的图表 PNG、勾选「含轮次明细」后工作表 3 有逐轮次行。

  * 「导出当前图 PNG」单图下载正常。

  * 分位兜底：构造一个 summary 缺 median/p90 的历史 job，确认分位图与统计表仍显示完整数值（来自 attempts 前端计算）。

  * 结果页 `/results` 已无趋势图区块，列表+详情+删除导出正常。

  * 统计摘要面板与异常高亮显示正确。

***

## 不做的事

* 不修改后端 API（现有接口已满足，分位由前端兜底计算）。

* **会**删除 `ResultsPage.vue` 的趋势图区块及无引用的 `MetricsChart.vue`（趋势图移动到观测页）。

* 本次不做：基线对比、维度分组着色、视图预设、图表全屏、自动刷新、SVG 导出（见「后续增强」）。

* 不引入 svg/zip 等额外依赖（仅新增 `exceljs`）。

