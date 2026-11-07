# 架构

Gleanery 是本地运行、单用户的应用。用户和 Agent 对话，Agent 起草采集计划，用户批准后，应用在专用 Chrome 里按保守限速采集公开内容，再由 Agent 查询和整理。设计理由见 [ADR](adr/)，术语见 [GLOSSARY.md](../GLOSSARY.md)。

## 进程结构

- **一个 Python 进程**：FastAPI、Pydantic AI 的 Agent 和采集执行器跑在同一个 asyncio 循环里。
- **Chrome**：由应用管理的子进程，每个平台一个配置目录，通过 CDP 连接。
- **前端**：Vite + React，构建产物由 FastAPI 同源托管，运行时不需要 Node。
- **数据**：SQLite（WAL）放在用户数据目录，可用 `GLEANERY_DATA_DIR` 指定。

## 前后端通信

| 通道 | 用途 |
|---|---|
| `POST /api/chat` | 对话流，审批结果也走这里 |
| REST JSON | 计划、任务、数据集、报告、导出、设置。TS 类型从 OpenAPI 生成 |
| `GET /api/events`（SSE） | 全局事件：进度、登录态变化、风控暂停。前端收到后重新拉取数据 |

## 模块

```
backend/gleanery/
  app.py        装配与生命周期
  api/          REST 与对话路由
  agent/        Agent、工具、系统提示、每轮注入
  collect/      计划、队列、平台 worker、限速、平台状态
  platforms/    bili/ xhs/：驱动、解析器、风控判定
  browser/      Chrome 进程与 CDP
  store/        ORM、仓储、Alembic 迁移、只读视图
  query/        Agent 的查询与只读 SQL
  report/       报告、引用解析
  export/       Excel、CSV、Markdown
  llm/          模型提供商与配置
frontend/src/   路由、组件、API 客户端
```

依赖方向是 `api`、`agent` → `collect`、`store`、`export`；`collect` → `platforms`、`store`；`platforms` → `browser`。`platforms` 和 `browser` 不知道 Agent 的存在。

## 采集

- **页面驱动**：应用打开真实页面，读取页面自己发出的请求的响应和 SSR 状态，不实现任何签名算法（[ADR-0001](adr/0001-page-driven-fetching.md)）。
- **计划是审批闸门**：Agent 起草的计划存为草稿，用户批准后才开始（[ADR-0002](adr/0002-plan-draft-and-approval-gate.md)）。Agent 没有直接取数的工具（[ADR-0005](adr/0005-agent-has-no-direct-fetch-tools.md)）。
- **执行**：任务表就是队列，每个平台一个串行 worker，不同平台可以并行。
- **风控即停**：出现风控信号时，任务暂停，平台进入冷却或转为需要登录。继续和解锁只能由用户在界面上操作。

## Agent

- 需要用户审批的工具只有三个：`start_collection`、`remove_from_dataset`、`delete_dataset`。
- 读数据、分析、写报告可以连续执行。Agent 不等待采集，任务状态在下一轮注入给它。
- 计划带后续意图时，采集全部完成后由后端自动发起一轮 Agent。

## 数据

- **内容库**是全局的，数据集只记成员关系（[ADR-0004](adr/0004-global-content-library.md)）。
- **Agent 查询**走只读的 `v_*` 视图。平台返回的文本都视为不可信数据。
- **报告**是 Markdown，用 `[[c:id]]`、`[[m:id]]` 引用内容和评论（[ADR-0006](adr/0006-report-as-markdown-with-citations.md)）。

## 模型提供商

支持 OpenAI 兼容接口、Anthropic 和 ChatGPT 套餐。ChatGPT 套餐走官方的 Sign in with ChatGPT（[ADR-0003](adr/0003-chatgpt-plan-via-siwc.md)）。凭证存在系统钥匙串，不进前端，也不写日志。

## 本地安全

- 只绑 `127.0.0.1`，校验 `Host`，写操作校验 `Origin`。
- 每次启动生成随机令牌，经 URL 换成 HttpOnly Cookie。
- 应用单实例运行。

## 测试

- 自动化测试不接真模型，也不碰真站点。
- 解析器用脱敏的 fixture 做快照测试，`just check` 带泄漏扫描。
- 端到端测试用 Playwright 和假 `Fetcher`。
