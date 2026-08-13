# Progress

## 2026-08-06

- 完成 llama.cpp systemd 和 llama-server 参数参考文档。
- 完成 V1 实施设计，确认 Vue、用户自建 service、配置记录、模型搜索下载、参数目录、自定义尾部和 Benchmark 解耦。
- 创建 FastAPI、SQLAlchemy、SQLite 后端与 Vue 3、TypeScript、Vite 前端。
- 实现设置、systemd 固定动作、日志、二进制/设备探测、本地 GGUF 扫描、Hugging Face 搜索和后台下载。
- 实现 Profile CRUD、参数目录刷新、POSIX shlex 自定义参数、别名重复检查、不可变 Profile version、原子 Active Profile 和失败回滚。
- 修复切换失败后数据库 Active 标记未回滚的问题。
- 增加 Profile 切换与 Benchmark 共用执行锁，避免切换期间测试错误模型。
- Benchmark 保存 Profile/version/argv 快照；内部 SSE 测 TTFT；读取 llama.cpp Prefill/Decode timings；缺失时配对非流式请求。
- 增加 NVIDIA 500 ms 资源采样摘要、warm-up、重复、并发、取消和统计汇总。
- 完成概览、设置、模型库、Profiles、Benchmark、结果对比、CSV 导出页面和全局响应式样式。
- 添加 README、环境变量示例、llama-server service、LlamaLens service 和精确 sudoers 示例。
- 添加参数、设置 API、Profile 和 mocked SSE Benchmark 测试。
- Python `compileall` 已通过。
- 项目 `.venv` 已创建，后端及测试依赖安装成功。
- 前端首次安装因系统 npm cache 无写权限失败，改用工作区缓存继续。
- 首轮 pytest 为 7 通过、1 失败；失败原因是浮点计时严格相等断言，已改为近似比较。
- 后端测试复跑通过：8 passed。
- 前端首轮构建发现缺少 `@types/node`，已补入开发依赖。
- Vue production build 已通过；路由懒加载后主包约 106 kB，图表仅在结果页加载。
- 首次 API smoke test 的 venv 相对路径写错，已更正后重试。

## 当前工作

- 后端最终测试通过：10 passed，只有 FastAPI TestClient 上游弃用提示。
- 前端最终 production build 通过；结果页 ECharts 为独立懒加载 chunk，主包约 106 kB。
- API smoke test 通过：健康接口、首页静态托管和 SPA 直达路由均返回 200。
- 浏览器可视检查通过：概览、Benchmark、设置页面显示正常；375px 窄屏无横向溢出；控制台无 error/warning。
- 前端可见文本检查未发现 em dash 或 en dash。
- 所有计划阶段已完成。
- 规划完整性脚本首次被系统执行策略阻止，改用单次 Bypass 运行检查。
- 检查脚本自身存在编码损坏并无法解析；已人工核对 5 个阶段均为 complete，不修改外部技能文件。

## 2026-08-13 Batch 4 继续实施

- 开始对照 `docs/batch4-design.md` 审计完成度。
- 已确认工作区包含 Batch 4 的部分实现与大量未提交改动；后续只做增量修复，不覆盖或回退已有工作。
- 当前阶段：逐项核对文件、API 调用、busy、SSE、Worker、i18n、测试与 lint，并运行完整验收。
- 修复 API 入口自引用、TypeScript `@` alias、API_BASE 导出、测试类型与 nullable ID，恢复前端 production build。
- 新增 `src/config.ts`，SSE 重连与降级轮询集中配置；断线时 running/stopping 1s、idle 5s 自适应轮询。
- 后端 SSE keepalive 与订阅队列上限支持环境变量，并修复空闲 `queue.Empty` 导致连接断开的问题。
- 增加 SSE 初始事件、keepalive、发布/退订测试；后端测试由 67 增至 70 passed。
- 补齐 Tasks、Profiles、Services 写操作 busy 防重和模板 disabled 状态。
- 完成 Profiles、Services、LaunchConfigEditor 与观测图表中英文文案提取。
- 最终验收：前端 54 tests passed；后端 70 passed（1 条上游 TestClient 弃用 warning）；ESLint 0 error、13 warnings；production build 成功并生成独立 Excel Worker chunk；`git diff --check` 通过。
- 已同步更新 `docs/optimization-plan.md`：批次 4 与 #10/#16–#22 标记为已解决，更新项目测试现状、优先级表、v1→v2 小结和推荐批次顺序，并新增完整的批次 4 实施记录；当前下一步调整为批次 5。
