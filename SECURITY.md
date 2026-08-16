# 安全策略

## 当前安全边界

LlamaLens 会管理本机 systemd service、模型目录和 Benchmark 任务。默认监听 `127.0.0.1`，但当前 MVP 不提供完整的多用户权限模型，也不应直接暴露到公网。

如果需要远程访问，请优先使用 SSH 隧道，或在前面配置带 TLS、认证和访问控制的 Nginx/Caddy。设置 `LLAMALENS_API_TOKEN` 后，非 loopback 请求需要 Bearer token；设置 `LLAMALENS_REQUIRE_AUTH=1` 可让 loopback 也强制认证。

## 不要提交的内容

- `.env` 和真实的 `LLAMALENS_API_TOKEN`
- SQLite 数据库、模型文件和下载缓存
- 生产环境 systemd unit、sudoers 文件和包含主机信息的日志

## 报告漏洞

请不要在公开 issue 中发布可直接利用的漏洞、凭据或完整攻击步骤。优先使用 GitHub 仓库的 **Security / Private vulnerability reporting**；如果仓库尚未启用该功能，请先联系维护者并提供：影响范围、复现步骤、受影响版本、临时缓解措施和安全的联系方式。

在问题修复并发布前，请避免公开未修复漏洞的细节。这个项目目前没有承诺固定的响应或修复时间。
