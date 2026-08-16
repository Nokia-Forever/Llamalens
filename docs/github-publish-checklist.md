# GitHub 发布检查清单

这份清单用于把当前工作区整理成可公开仓库。它不会替代代码审计，也不会自动替你删除已经提交到 Git 历史中的文件。

## 1. 提交前检查

```bash
git status --short
git diff --check
git ls-files | sort
git log --oneline -10
```

确认没有以下内容：

- `.env`、API token、私钥、生产日志或数据库。
- GGUF/模型文件、下载缓存和本地数据目录。
- `node_modules`、`dist`、`__pycache__`、`*.tsbuildinfo`、`*.egg-info`。
- 编辑器或本地自动化工具目录，例如 `.trae/`。

注意：`.gitignore` 只会阻止未来新增文件。已经被 Git 跟踪的文件仍需单独处理，例如：

```bash
git rm -r --cached .trae
git rm --cached frontend/tsconfig.app.tsbuildinfo frontend/tsconfig.node.tsbuildinfo
git rm -r --cached backend/llamalens.egg-info
```

执行前请确认这些目录不是你希望随仓库发布的项目资产；如文件曾经包含凭据，还需要轮换凭据并清理 Git 历史。

## 2. 依赖和测试

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e "./backend[test]"
python -m pytest backend/tests

cd frontend
npm ci
npm test -- --run
npm run lint
npm run build
```

生产部署还应在目标 Linux 主机上验证 systemd、文件权限、模型目录可读写性和 `llama-server --help` 参数目录刷新。

## 3. GitHub 仓库设置

1. 选择仓库可见性和默认分支保护策略。
2. 在仓库 About 中补充项目简介、主题词和用途说明。
3. 确认仓库根目录的 `LICENSE` 与实际版权主体一致；当前工作区已准备 Apache License 2.0 文本。
4. 启用 Dependabot、secret scanning 和 push protection（如果仓库计划公开）。
5. 配置 Issues、Discussions 或 Security Advisories 的入口，并让它们与 `CONTRIBUTING.md`、`SECURITY.md` 保持一致。

## 4. 首次发布后的快速验证

在干净目录中克隆仓库，按照 README 从头执行安装、构建和启动命令。确认：

- 根目录 README 链接都能打开。
- 不依赖提交者本机的绝对路径、环境变量或缓存。
- 未配置 token 时，loopback 开发流程仍符合 README；非 loopback 部署按安全文档要求配置认证。
- 生成的 SQLite 数据和模型目录位于仓库外。
