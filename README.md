# Gleanery

一个本地运行、单用户的信息采集与整理应用。你用自然语言告诉 Agent 想了解什么，它起草采集计划，你批准后从 B 站和小红书采集公开内容，再整理成数据集和带引用的报告。

所有数据都留在你自己的电脑上。

## 功能

- **对话驱动**：Agent 起草采集计划，由你在卡片上检查和批准，它没有直接取数的工具。
- **两个平台**：B 站和小红书，可以并行。应用驱动一个专用 Chrome 的真实页面，由你本人扫码登录。
- **数据集**：浏览、筛选、调整，导出 Excel、CSV 和 Markdown。
- **报告**：Markdown 加引用，可以编辑和导出；采集完成后可以自动续写。
- **三类模型提供商**：OpenAI 兼容接口（含 DeepSeek、通义、OpenRouter、Ollama）、Anthropic、ChatGPT 套餐。

## 使用声明

- 只采集账号本来就能看到的公开内容，用于个人研究。
- 请遵守各平台的用户协议。
- 默认保守限速，遇到风控即停止。
- 本项目**不提供**签名算法、代理池、多账号，也不提供绕过验证码的能力。

建议用专用小号登录平台，不要用主号。

## 快速开始

需要 Python 3.13、[uv](https://docs.astral.sh/uv/)、Node.js、[pnpm](https://pnpm.io/)、[just](https://just.systems/) 和本机的 Chrome。

```bash
just setup
```

```bash
cd frontend && pnpm build
```

```bash
cd backend && uv run gleanery
```

应用只监听 `127.0.0.1`，启动后会打开浏览器。在设置的"模型"标签里配好一个模型，再到左栏的"平台账号"页扫码登录平台，就可以开始对话。

- 数据目录默认在系统的用户数据目录下，可以用环境变量 `GLEANERY_DATA_DIR` 指定。
- 换机器或重装前，备份数据目录。

## 模型与凭证

| 提供商 | 需要什么 |
|---|---|
| OpenAI 兼容 | Base URL 和 API Key，本地模型可以不填 Key |
| Anthropic | API Key |
| ChatGPT 套餐 | 点 "Continue with ChatGPT" 登录，需要 Plus 或 Pro |

- API Key 和 token 存在系统钥匙串。钥匙串不可用时退回数据目录里的 0600 文件，设置里会明示。
- 凭证不进前端，也不写日志。
- 数据库和导出文件不额外加密，请开启系统磁盘加密（FileVault / BitLocker）。
- ChatGPT 套餐走 OpenAI 官方的 Sign in with ChatGPT，用量计入你的套餐额度，与 Codex 共享，Plus 还有 5 小时窗口。额度用尽时当前这一轮停止，应用不会自动切换到别的提供商。这条路径目前是 OpenAI 的预览功能，随时可能变化。

## 文档

- [架构](docs/architecture.md)：进程结构、通信、采集和数据模型。
- [架构决策](docs/adr/)。
- [术语表](GLOSSARY.md)。
- [贡献指南](CONTRIBUTING.md)。

## 关于 MediaCrawler

本项目参考 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) 的技术思路。MediaCrawler 采用《非商业学习使用许可证 1.1》，本项目**净室重写**，不复制其源码。

## 协议

[Apache-2.0](LICENSE)。第三方声明见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES)。名称 Gleanery 不随协议授权。
