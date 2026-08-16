# 贡献指南

感谢你为 LlamaLens 提交改进。这个项目同时包含 Python 后端、Vue 前端和 Linux 部署示例，提交前请尽量把变更限制在清晰的边界内。

## 开始开发

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e "./backend[test]"

cd frontend
npm ci
```

Windows PowerShell 可使用 `.venv\Scripts\python.exe` 和 `npm.cmd`。

## 本地检查

```bash
python -m pytest backend/tests
cd frontend
npm test -- --run
npm run lint
npm run build
```

如果没有 Linux systemd 或 llama.cpp，不要伪造部署结果；请使用后端测试和 mock 适配层，并在 PR 描述中说明未覆盖的真实环境。

## 提交规范

- 一个提交尽量只解决一个问题，并写清楚行为变化。
- 不提交 `.env`、token、模型文件、数据库文件、`node_modules`、构建目录或本地 IDE 工具目录。
- 修改 API 时同步更新类型、测试和相关文档。
- 修改 systemd、sudoers 或下载逻辑时，必须在 PR 中写出权限和安全影响。
- UI 变更请说明桌面和窄屏布局是否检查过。

## Pull Request 内容

PR 至少包含：

1. 变更目的和用户可见行为。
2. 测试命令及结果；未执行的检查要说明原因。
3. 配置、数据库迁移、部署步骤或兼容性影响。
4. 若涉及安全边界，说明默认行为是否改变。

## Issue

报告问题时请附上操作系统、Python/Node.js 版本、复现步骤、相关日志和脱敏后的配置。不要在公开 issue 中粘贴 token、模型路径中的敏感信息或完整 service 日志。
