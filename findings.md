# Findings

## 已确认需求

- 前端使用 Vue。
- 用户在 Web 设置中登记 llama.cpp service 名、unit 路径、scope、控制命令、二进制、模型目录和网络地址。
- systemd unit 与权限由用户自行创建和配置。
- 模型库支持本地扫描、Hugging Face 搜索与下载。
- Profile 只要求名称和模型；所有已知参数可搜索添加；用户可逐行输入 `-np 1` 一类自定义参数。
- 重复参数提示但不阻止，保持最终 argv 顺序。
- Benchmark 与启动 Profile 解耦。Prompt、max_tokens、timeout、temperature、seed、stop、warm-up、重复和并发均可编辑。
- 前端不显示流式 token，但后端内部使用 SSE 精确测 TTFT。
- 核心指标是 TTFT、Prefill tok/s、Decode tok/s。

## 技术决定

- FastAPI + SQLAlchemy + SQLite；Vue 3 + TypeScript + Vite + Pinia + Vue Router + ECharts。
- systemd 和 llama.cpp 交互位于适配层，Windows 开发环境使用 mock 验证。
- 最终命令始终是 argv 数组；自定义参数使用 `shlex.split`，不经过 shell。
- 系统级控制命令只允许 `systemctl` 或 `sudo -n systemctl` 的固定形式。
- Profile 切换和 Benchmark 使用同一进程内执行锁，避免结果归属错误。
- 每个 Benchmark 保存当前 Profile version 和完整 argv 快照。
- UI 是高密度技术管理工具，不套用营销页视觉模式；采用单一青绿色强调色、统一 8-10px 圆角、完整 loading/empty/error 状态。

## 指标基线

- TTFT：请求开始到首个非空内容 chunk 的客户端单调时钟差。
- Prefill tok/s：`timings.prompt_per_second`。
- Decode tok/s：`timings.predicted_per_second`。
- Client Decode：当输出 token 大于 1 时，`(predicted_n - 1) / (last_content_time - first_content_time)`。
- 流事件无 timings 时，执行配对非流式请求并标记 `measurement_mode=paired`。

## 外部资料基线

- llama.cpp 参数参考基于上游 `common/arg.cpp` 提交 `c8e03ce8122b7af76f836d53efde6df1ce5ec437`。
- 目标机实际 `llama-server --help` 始终高于内置种子目录，应用提供运行时刷新。

## 环境发现

- 工作区不是 Git 仓库。
- `rg.exe` 无法运行。
- `npm.ps1` 被执行策略阻止，应使用 `npm.cmd`。
- 默认 `python` 指向另一个项目环境；可用全局解释器为 `C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe`。
- Node.js 版本为 24.16.0，npm 版本为 11.13.0。
