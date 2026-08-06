# LlamaLens V1 实现计划

## 目标

实现可运行的单机 V1：FastAPI/SQLite 后端、Vue 3 前端、模型扫描与下载、Profile 参数目录和自定义尾部、固定 systemd service 控制、TTFT/Prefill/Decode Benchmark、结果对比与部署文档。

## 设计基线

- systemd unit 和 sudoers 全部由用户创建，程序只记录并使用固定配置。
- Web 默认监听 `127.0.0.1`，用户选择 `0.0.0.0` 时显示无认证风险。
- Profile 最小必填为名称和模型；已知参数从目录添加；自定义参数用 shlex 解析后追加。
- 重复参数只警告，不阻止；最终 argv 顺序不变。
- Benchmark 与 Profile 请求配置解耦；Prompt 和请求参数由用户输入。
- 内部 SSE 测量 TTFT，Prefill 和 Decode 优先使用 llama.cpp timings。

## 阶段

| 阶段 | 状态 | 验收 |
|---|---|---|
| 1. 项目骨架与数据模型 | complete | 后端、前端、SQLite schema、参数种子目录和基础路由已创建 |
| 2. 后端 API 与系统适配 | complete | 设置、扫描/下载、Profile CRUD/切换回滚、systemd、Benchmark 与结果 API 已实现 |
| 3. Vue 产品界面 | complete | 概览、设置、模型、Profile、Benchmark、结果页与响应式样式已实现 |
| 4. 测试与联调 | complete | 10 项 Python 测试、前端构建、API smoke test 和浏览器检查通过 |
| 5. 部署与文档 | complete | README、示例 unit、sudoers、环境变量和参数参考完整 |

## 非目标

- 不自动创建 systemd service 或 sudoers。
- 不实现 Web 账号、TLS、集群或多节点管理。
- 不删除本地模型。
- Windows 开发机不具备真实 systemd、GPU 和 llama-server，相关行为使用适配层和 mock 验证。

## 错误记录

| 错误 | 次数 | 处理 |
|---|---:|---|
| `rg.exe` 在当前 Windows 环境无法运行 | 1 | 使用 PowerShell `Get-ChildItem` 和 `Select-String` |
| 工作区不是 Git 仓库 | 1 | 不依赖 git diff，按文件清单审查 |
| `npm.ps1` 被 PowerShell execution policy 阻止 | 1 | 使用 `npm.cmd` |
| 默认 `python` 指向另一个无 pip/SQLAlchemy 的项目虚拟环境 | 1 | 使用全局 Python 3.13 创建项目本地 `.venv` |
| 首次组合补丁因 operations.py 上下文不匹配失败 | 1 | 拆成小补丁并按实际导入重新应用 |
| `npm.cmd install` 无权写系统 npm cache | 1 | 改用工作区 `.npm-cache`，不修改全局配置 |
| SSE 测试对浮点毫秒做严格相等比较失败 | 1 | 使用 `pytest.approx` 检验计时浮点值 |
| Vue 构建缺少 Node 类型定义 | 1 | 添加 `@types/node` 开发依赖 |
| Backend 目录 smoke test 使用了错误的相对 venv 路径 | 1 | 改为 `..\\.venv\\Scripts\\python.exe` |
| 规划检查脚本被 PowerShell execution policy 阻止 | 1 | 仅对该只读检查脚本使用单次 `-ExecutionPolicy Bypass` |
| 规划检查脚本绕过策略后因脚本自身编码损坏无法解析 | 1 | 不修改技能安装文件，改为直接核对阶段表全部为 complete |
