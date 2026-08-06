# LlamaLens Linux 部署

项目已放在：

```text
~/llamalens/repo
```

以下假设 LlamaLens 和 `llama-server` 使用同一个普通 Linux 用户运行。先查看用户名和项目绝对路径：

```bash
whoami
realpath ~/llamalens/repo
```

下面 systemd 示例中的 `<用户名>` 和 `/home/<用户名>` 必须替换成实际值。systemd 不会展开 `~`。

## 1. 构建

要求 Python 3.11+、Node.js 20.19+（推荐 Node.js 22）。

```bash
cd ~/llamalens/repo

python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e ./backend

./.venv/bin/python -m pip install --retries 10 --timeout 120 \
  -i https://pypi.tuna.tsinghua.edu.cn/simple \
  -e ./backend

cd frontend
npm ci
npm run build
```

如果项目中已经包含 `frontend/dist/index.html`，可以跳过 Node.js 构建。

## 2. 数据目录

```bash
sudo install -d -o <用户名> -g <用户名> -m 0750 /var/lib/llama-lens
```

模型目录必须允许该用户读取；如果使用网页下载模型，还需要写权限。

## 3. 创建 LlamaLens service

```bash
sudo vim /etc/systemd/system/llama-lens.service
```

```ini
[Unit]
Description=LlamaLens Console
After=network.target

[Service]
Type=simple
User=<用户名>
Group=<用户名>
WorkingDirectory=/home/<用户名>/llamalens/repo/backend
Environment=PYTHONPATH=/home/<用户名>/llamalens/repo/backend
Environment=LLAMALENS_DATA_DIR=/var/lib/llama-lens
Environment=LLAMALENS_FRONTEND_DIST=/home/<用户名>/llamalens/repo/frontend/dist
ExecStart=/home/<用户名>/llamalens/repo/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 3000 --proxy-headers
Restart=on-failure
RestartSec=3
UMask=0027

[Install]
WantedBy=multi-user.target
```

启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now llama-lens.service
sudo systemctl status llama-lens.service
```

默认访问地址：`http://127.0.0.1:3000`。

远程访问建议使用 SSH 隧道：

```bash
ssh -L 3000:127.0.0.1:3000 <用户名>@<服务器IP>
```

## 4. 修改 llama-server service

在现有 `llama-server.service` 的 `[Service]` 中使用 LlamaLens runner：

```ini
[Service]
User=root
Group=<用户名>
WorkingDirectory=/home/<用户名>/llamalens/repo/backend
Environment=PYTHONPATH=/home/<用户名>/llamalens/repo/backend
ExecStart=/home/<用户名>/llamalens/repo/.venv/bin/python -m app.runner --profile /var/lib/llama-lens/active-profile.json
Restart=on-failure
RestartSec=3
TimeoutStartSec=15min
TimeoutStopSec=2min
LimitNOFILE=1048576
```

修改后执行：

```bash
sudo systemctl daemon-reload
```

先不要立即重启 `llama-server`。在 Web 中创建并激活 Profile 后，程序会生成 Active Profile 并自动重启服务。

## 5. 配置 sudoers(llama-lens 配置了root 用户就不需要这个配置)

```bash
sudo visudo -f /etc/sudoers.d/llama-lens
```

写入以下内容，并将 `<用户名>` 替换为实际用户：

```sudoers
<用户名> ALL=(root) NOPASSWD: /usr/bin/systemctl status llama-server.service
<用户名> ALL=(root) NOPASSWD: /usr/bin/systemctl start llama-server.service
<用户名> ALL=(root) NOPASSWD: /usr/bin/systemctl stop llama-server.service
<用户名> ALL=(root) NOPASSWD: /usr/bin/systemctl restart llama-server.service
```

验证：

```bash
sudo visudo -cf /etc/sudoers.d/llama-lens
sudo -u <用户名> /usr/bin/sudo -n /usr/bin/systemctl status llama-server.service
```

不要配置 `NOPASSWD: ALL` 或任意 `systemctl *` 权限。

## 6. Web 首次设置

```text
Service 名称：llama-server.service
Unit 文件：/etc/systemd/system/llama-server.service
Systemd 范围：system
控制命令：/usr/bin/sudo -n /usr/bin/systemctl
llama-server 路径：实际的 llama-server 二进制路径
Active Profile：/var/lib/llama-lens/active-profile.json
模型目录：你的 GGUF 模型目录
Llama Host：127.0.0.1
Llama Port：8080
```

Llama Host/Port 会自动写入 Profile 的最终 `--host`、`--port`，同时用于健康检查和 Benchmark。不要在 Profile 中重复添加这两个参数。

保存后依次：刷新参数目录、扫描模型、创建 Profile、激活 Profile、运行 Benchmark。

## Root 权限说明

只有这些操作需要 root：创建或修改 systemd unit、配置 sudoers、创建系统数据目录、执行 `daemon-reload` 和首次启用服务。

LlamaLens 和 `llama-server` 本身都使用普通用户运行。网页只通过 sudoers 白名单控制固定的 `llama-server.service`。

## 查看日志

```bash
sudo journalctl -u llama-lens.service -n 100 --no-pager
sudo journalctl -u llama-server.service -n 100 --no-pager
```
