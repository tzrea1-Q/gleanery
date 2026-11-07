# ChatGPT 套餐走官方 Sign in with ChatGPT，不借用 Codex 登录

ChatGPT 套餐这个 LLM 提供商，走 OpenAI 官方的 Sign in with ChatGPT 流程：用 Pydantic AI 的 `openai-chatgpt` provider，以 `dynamic_agent_client` 动态注册，PKCE + `127.0.0.1` 本地回调，拿到带 `chatgpt.tokens.use.direct` scope 的 token，以 `store:false` 直接调用公开的 `/v1/responses`。凭证由应用自己保存在系统钥匙串。我们**不用** Pydantic AI 现成的 `openai-codex` provider，也不读 `~/.codex/auth.json`、不复用 Codex CLI 的 client_id、不请求 `chatgpt.com/backend-api`。原因有三：SIWC 文档明确要求第三方不要请求 backend-api；refresh token 是单次轮换的，和 Codex CLI 共用同一个 token 会互相顶掉对方的登录；冒用第一方客户端处在条款的灰色地带。额度用尽时也不自动切换到其他提供商，因为那会悄悄花掉用户 API Key 的钱。

## Considered Options

- **`openai-codex` provider / 读 `~/.codex/auth.json`**：零注册、Pydantic AI 现成，但端点没有文档，会和 Codex CLI 抢 refresh token，有合规风险。被否。
- **`openai-codex` SDK 驱动 `codex app-server`**：跑的是 Codex 自己的 agent，我们的业务工具只能经 MCP 或 experimental 接口接入，token 刷新后还要重启 app-server。被否。

## Consequences

- 只有 Plus / Pro 可用。预览期参数受限，所以 Agent 层对所有提供商都不依赖 `temperature`、`max_tokens`、托管工具和 `previous_response_id`。
- 应用名（`agent_name_hint`）一旦改动，已有用户需要重新注册。如果正式发布时闭源，需要先向 OpenAI 申请。
