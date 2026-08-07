# LlamaLens

LlamaLens 是一个部署在 llama.cpp 推理机本机的轻量 Web 控制台。它可以创建和管理多个 `llama-server` systemd service，把模型和启动参数保存为可复用 Profile 模板，再复制到具体 Service 后显式部署，并用独立 Benchmark 请求测量：

- TTFT：请求开始到第一个实际内容 token 到达的时间。
- Prefill tok/s：llama.cpp 返回的 `timings.prompt_per_second`。
- Decode tok/s：llama.cpp 返回的 `timings.predicted_per_second`。
- Client Decode tok/s：按首个和最后一个内容 token 的客户端时间戳计算，用于核对服务端指标。

前端使用 Vue 3，后端使用 FastAPI、SQLAlchemy 和 SQLite。当前 MVP 假设 LlamaLens 以 root 运行，能够写入 `/etc/systemd/system` 并直接调用 `systemctl`；默认仍只监听本机地址。

## 当前能力

- 创建多个独立的 Llama Service，分别配置二进制、端口、运行用户、WorkingDirectory 和 systemd 参数。
- Profile 是独立启动模板，支持单模型 `--model/--alias` 和 Router `--models-dir/--models-preset/--models-max/--models-autoload`。
- Service 导入 Profile 时复制完整模型与 llama 参数；之后可独立修改，不与原 Profile 或其他 Service 联动。
- Service 分别保存 draft 与最后一次成功部署的 applied 快照；保存草稿不会自动重启。
- 在 `[Unit]`、`[Service]`、`[Install]` 中追加自定义指令，并在部署前预览、复制或下载完整 unit。
- 写入 unit 后执行 `daemon-reload`、`enable --now`，并支持启停、重启、日志、归档恢复和彻底删除。
- 扫描多个模型目录，搜索 Hugging Face GGUF 文件并创建后台下载任务。
- Profiles 与 Service 本地副本复用同一套模型、Router、参数目录和自定义参数编辑器。
- 从目标机 `llama-server --help` 刷新参数目录，并保留内置兼容目录。
- 自定义参数按行使用 POSIX `shlex` 分词并追加到最终 argv，例如 `-np 1`。
- 重复参数只警告、不阻止，别名也会归一后检查；最终顺序保持不变。
- 只有 Services 页面会显式写入 unit 并执行 `daemon-reload`、`enable --now` 和 `status`；Profile 页面没有激活操作。
- Benchmark 只能选择 Service 已成功部署的 applied 模型 alias，并保存完整 Service 与 applied 启动快照。
- 内部 SSE 测 TTFT，流结束事件读取 timings；缺少 timings 时执行有明确标记的配对非流式请求。
- 支持 warm-up、重复次数、并发、Prompt cache、stop、seed、temperature、timeout 和额外 JSON 参数。
- 展示 median、p10、p90、min、max、失败次数、每轮证据和 CSV 导出。

## 开发运行

要求 Python 3.11+、Node.js 20+。

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e "./backend[test]"

cd frontend
npm install
npm run build
cd ../backend

LLAMALENS_DATA_DIR=../data python -m app.web
```

首次运行默认监听 `127.0.0.1:3000`。如果前端尚未构建，可以分别运行：

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

cd frontend
npm run dev
```

Vite 会把 `/api` 代理到 `127.0.0.1:8000`。

## Linux 部署

当前 MVP 会为 Services 页面创建的服务执行 systemd 命令。LlamaLens 自身仍需要先手工安装：

1. 把项目放到 `/opt/llama-lens`，创建虚拟环境并构建前端。
2. 创建 `/var/lib/llama-lens` 数据目录，并让 LlamaLens 可写。
3. 创建 LlamaLens 自身的 service，并以 `User=root` 运行。
4. 在 Profiles 页面创建单模型或 Router 启动模板。
5. 在 Services 页面填写 `llama-server` 路径、端口、运行用户和 systemd 自定义指令，再导入一个 Profile。
6. 按需编辑 Service 本地副本，生成 unit 预览，确认后点击“应用并部署”。

Services 页面生成的 unit 名强制使用 `llamalens-*.service`，例如：

```text
Unit 名称: llamalens-qwen.service
llama-server: /opt/llama.cpp/build/bin/llama-server
Host: 127.0.0.1
Port: 8080
Alias: qwen
```

每个 Service 的 Host/Port 同时用于启动参数、健康检查和 Benchmark。Benchmark 页面先选择 Service，再选择该 Service 的 applied 快照中登记的模型 alias；只有草稿而未成功部署的 Service 不能测试。

### systemctl 是否需要 root

- 当前 MVP 直接以 root 运行 LlamaLens；不要把没有认证的管理端口暴露到公网。
- `status` 有时普通用户可以执行，但不要依赖不同发行版的默认策略。
- 用户级 service 使用 `systemctl --user`，不需要 root，但需要正确的用户会话或 linger 配置。
- LlamaLens 使用 `sudo -n`，权限没配置好时会直接报错，不会弹出密码输入框。

如果要读取系统 journal，可以把运行用户加入发行版对应的日志读取组，常见为 `systemd-journal`。这是用户手动完成的系统配置。

### 文件权限

`/etc/systemd/system` 与 LlamaLens 数据目录必须只允许受信任的管理员写入。模型目录至少要让各 llama.cpp Service 的运行用户可读。若启用 Web 下载，还要让 LlamaLens 用户对选定下载目录可写。

## Web 暴露风险

V1 没有账号密码。默认只能监听 `127.0.0.1`。如果设置为 `0.0.0.0`，任何能访问该端口的人都可能：

- 修改模板、部署或重启任意受管 Service；
- 发起大文件下载；
- 运行消耗 GPU/CPU 的 Benchmark；
- 查看本机配置和 service 日志。

需要远程访问时，建议保持 LlamaLens 监听 loopback，通过 SSH tunnel 访问；或者在前面放置带 TLS 和认证的 Nginx/Caddy。

## Benchmark 说明

Benchmark 请求配置和 Service 启动配置是两套数据。`max_tokens`、Prompt、timeout、temperature 等只进入 HTTP 请求，不会写入 systemd Service。每个任务保存创建时的 applied 启动快照，因此后续修改 Profile、Service 草稿或重新部署都不会改变历史结果。

为了准确测 TTFT，后端会在内部设置 `stream=true` 并读取 SSE，但 Vue 页面不会显示逐 token 输出。Prefill 和 Decode 的主要值只读取 llama.cpp timings，避免把 HTTP 总耗时误当成推理速度。

当流式最终事件没有 timings 时，后端会再发一次相同参数的非流式请求读取 timings，并把该轮标记为 `paired`。此时 TTFT 来自第一条请求，Prefill/Decode 来自第二条请求，结果页会明确显示测量模式。

`cache_prompt=false` 是默认值。若用户开启 Prompt cache，重复测试可能主要反映缓存命中性能，结果不可与冷 Prefill 直接混在一起比较。

## 测试

```bash
./.venv/bin/python -m pytest backend/tests
cd frontend && npm run build
```

Windows PowerShell 使用 `.venv\Scripts\python.exe` 和 `npm.cmd`。

## 参考文档

- [实现设计](docs/implementation-design.md)
- [llama.cpp systemd 与 llama-server 参数参考](docs/llama-cpp-systemd-service-parameters.md)
