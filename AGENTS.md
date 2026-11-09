# Gleanery 开发约定

给在本仓库里写代码的 Agent（含 Codex）看的约定。

- **先读**：`docs/architecture.md`（架构）、`docs/adr/`（设计决策）、`GLOSSARY.md`（术语）。进行中的开发契约在 `docs/dev/`。
- **公开仓库**：真账号的操作记录、真站风控细节、外部项目的源码笔记不写进仓库，维护者把这类记录放在主检出下被忽略的 `.private/`，不存在就跳过。提交钩子和 `just check` 会扫描本机路径、个人邮箱、密钥和 Cookie 值；确认是误报才在该行加 `leak-scan: allow`。
- **命名**：包名、命令、数据目录都是 `gleanery`，不是 `gleaner`。
- **净室**：不复制 MediaCrawler 的源码，也不参照着改写。
- **语言**：文档、注释、界面文案、提交信息用中文；标识符用英文。注释只写代码表达不了的原因和约束。
- **依赖**：版本已经锁定在 `backend/uv.lock` 和 `frontend/pnpm-lock.yaml`。不要新增或升级依赖，确实需要时在报告里说明理由。
- **后端**：Python 3.13，用 `uv run` 执行。时间存 UTC 毫秒整数。路由抛 `gleanery.api.errors.ApiError`，错误体为 `{code, message, hint}`。不写 `temperature`、`max_tokens`、`openai_*` 这类模型设置。日志里不出现 Key、token、cookie。
- **前端**：只用相对 URL。用 `pnpm format`（Prettier）格式化。REST 走 `src/api/client.ts`。
- **界面**：改页面、组件或样式之前读 `docs/frontend.md`（风格、组件选型、交互、完成标准）。
- **测试**：自动化测试不接真模型（`ALLOW_MODEL_REQUESTS=False`），用 `FunctionModel` 或假服务器。存储测试用真 SQLite 临时文件。
- **检查**：`just check`（全部）、`just pre-commit`（快的部分）。改了 API 契约要跑 `just gen-api`。
