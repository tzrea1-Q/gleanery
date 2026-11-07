# 贡献指南

欢迎提 issue 和 PR。动手之前先读 [AGENTS.md](AGENTS.md)（开发约定）、[docs/architecture.md](docs/architecture.md)（架构）和 [GLOSSARY.md](GLOSSARY.md)（术语）。

## 不接受的 PR

下面这些改动不会合入，无论实现得多好：

- **签名或逆向**：实现平台的请求签名算法，或者逆向平台的私有接口。Gleanery 通过驱动真实页面取数，见 [ADR-0001](docs/adr/0001-page-driven-fetching.md)。
- **绕过风控**：绕过验证码、风控或封禁，包括代理池、多账号轮换和指纹伪造。遇到风控时应用会停下，这是设计，不是缺陷。
- **提速到默认下限以下**：调低限速和间隔的下限，或者提供绕过下限的开关。

## 净室

本项目参考 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) 的技术思路，但是净室重写。MediaCrawler 采用非商业学习使用许可证，不得复制它的源码，也不得参照着改写。

## 开发

需要 Python 3.13、[uv](https://docs.astral.sh/uv/)、Node.js、[pnpm](https://pnpm.io/) 和 [just](https://just.systems/)。

```bash
just setup
```

提交前跑：

```bash
just check
```

- `just pre-commit` 只跑快的部分，提交时由 git hook 调用。
- `just ci` 再加上端到端测试。
- 改了 REST 契约要跑 `just gen-api`。
- 改界面按 [docs/frontend.md](docs/frontend.md) 做，包括它的完成标准。
- 自动化测试不接真模型，也不碰真站点。
- 文档、注释、界面文案和提交信息用中文，标识符用英文。
- 依赖版本已锁定，不要顺手升级或新增。确实需要时在 PR 里说明理由。

## 真机冒烟

改了驱动、选择器或解析器，要用专用小号在真站手动走一遍受影响的流程，绝不用主号，一出现风控信号就停。提交 fixture 前必须脱敏，泄漏扫描会在 `just check` 里运行。

## 协议

提交贡献即表示你同意以 [Apache-2.0](LICENSE) 授权你的贡献。
