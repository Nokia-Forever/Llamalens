# LlamaLens

LlamaLens 是一个部署在 llama.cpp 推理机本机的轻量 Web 控制台。它管理用户已经创建的 `llama-server` systemd service，把模型和启动参数保存为 Profile，并用独立 Benchmark 请求测量：

- TTFT：请求开始到第一个实际内容 token 到达的时间。
- Prefill tok/s：llama.cpp 返回的 `timings.prompt_per_second`。
- Decode tok/s：llama.cpp 返回的 `timings.predicted_per_second`。
- Client Decode tok/s：按首个和最后一个内容 token 的客户端时间戳计算，用于核对服务端指标。

前端使用 Vue 3，后端使用 FastAPI、SQLAlchemy 和 SQLite。V1 不创建 service、不修改 sudoers、不保存 root 密码，也没有 Web 登录。

## 当前能力

- 登记固定的 service 名称、unit 路径、system/user scope、控制命令和 llama-server 路径。
- 扫描多个模型目录，搜索 Hugging Face GGUF 文件并创建后台下载任务。
- Profile 只要求名称和 GGUF 模型；其它参数从可搜索目录按需添加。
- 从目标机 `llama-server --help` 刷新参数目录，并保留内置兼容目录。
- 自定义参数按行使用 POSIX `shlex` 分词并追加到最终 argv，例如 `-np 1`。
- 重复参数只警告、不阻止，别名也会归一后检查；最终顺序保持不变。
- 原子写入 Active Profile，重启失败时恢复文件和数据库 Active 标记。
- Benchmark 与 Profile 切换使用同一执行锁，避免测试期间更换模型。
- Benchmark 保存当前 Profile、Profile version 和完整 argv 快照。
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

下面仅是参考流程。LlamaLens 不会替你执行这些命令。

1. 把项目放到 `/opt/llama-lens`，创建虚拟环境并构建前端。
2. 创建非 root 用户 `llama-lens`，让它可以写 `/var/lib/llama-lens` 和需要下载模型的目录。
3. 由用户创建 llama.cpp service。可参考 [llama-server.service.example](deploy/llama-server.service.example)。
4. 由用户创建 LlamaLens service。可参考 [llama-lens.service.example](deploy/llama-lens.service.example)。
5. 如果 llama.cpp 使用系统级 service，手动配置只允许固定 unit 的 sudoers。可参考 [sudoers.example](deploy/sudoers.example)。
6. 在 Web 设置页填写实际路径和 llama-server 地址/端口，再从 Profiles 页面刷新本机参数目录。

推荐的设置值：

```text
Service 名称: llama-server.service
Systemd 范围: system
控制命令: /usr/bin/sudo -n /usr/bin/systemctl
Active Profile: /var/lib/llama-lens/active-profile.json
Web Host: 127.0.0.1
Llama Host: 127.0.0.1
Llama Port: 8080
```

`Llama Host/Port` 有三项关联用途：自动加入每个 Profile 的最终启动命令（`--host`、`--port`）、切换 Profile 后执行健康检查、向同一地址发送 Benchmark 请求。因此一般不要再在 Profile 中重复添加 `--host` 或 `--port`，否则实际监听地址可能与健康检查、Benchmark 地址不一致。

### systemctl 是否需要 root

- 系统级 service 的 `start`、`stop`、`restart` 通常需要 root。LlamaLens 应以普通用户运行，并通过仅允许固定 unit 和固定动作的 sudoers 白名单获得权限。
- `status` 有时普通用户可以执行，但不要依赖不同发行版的默认策略。
- 用户级 service 使用 `systemctl --user`，不需要 root，但需要正确的用户会话或 linger 配置。
- LlamaLens 使用 `sudo -n`，权限没配置好时会直接报错，不会弹出密码输入框。

如果要读取系统 journal，可以把运行用户加入发行版对应的日志读取组，常见为 `systemd-journal`。这是用户手动完成的系统配置。

### 文件权限

`active-profile.json` 必须同时满足：

- LlamaLens 运行用户可创建和原子替换；
- llama.cpp service 运行用户可读取；
- 父目录不能对无关用户开放写权限。

模型目录至少要让 llama.cpp 用户可读。若启用 Web 下载，还要让 LlamaLens 用户对选定下载目录可写。

## Web 暴露风险

V1 没有账号密码。默认只能监听 `127.0.0.1`。如果设置为 `0.0.0.0`，任何能访问该端口的人都可能：

- 切换模型并重启 service；
- 发起大文件下载；
- 运行消耗 GPU/CPU 的 Benchmark；
- 查看本机配置和 service 日志。

需要远程访问时，建议保持 LlamaLens 监听 loopback，通过 SSH tunnel 访问；或者在前面放置带 TLS 和认证的 Nginx/Caddy。

## Benchmark 说明

Benchmark 配置和 llama.cpp 启动 Profile 是两套数据。`max_tokens`、Prompt、timeout、temperature 等只进入 HTTP 请求，不会写入 systemd service。

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
