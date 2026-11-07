# Gleanery 的唯一任务入口。

set shell := ["bash", "-euo", "pipefail", "-c"]

# uv.lock 记录的是官方源；环境里设了别的 UV_DEFAULT_INDEX 时，uv 会判定锁文件过期并改写它。
export UV_DEFAULT_INDEX := "https://pypi.org/simple"

default:
    @just --list

# 安装依赖并启用仓库自带的 git hook
setup:
    cd backend && uv sync
    cd frontend && pnpm install --frozen-lockfile
    cd frontend && pnpm exec playwright install chromium
    git config core.hooksPath .githooks

# 从后端导出 OpenAPI，再生成前端 TS 类型
gen-api:
    cd backend && uv run python -m gleanery.openapi openapi.json
    cd frontend && pnpm gen:api

# 完整检查：ruff、pyright、pytest，前端 tsc、eslint、vitest
check: check-backend check-frontend

check-backend:
    cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q

check-frontend:
    cd frontend && pnpm format:check && pnpm typecheck && pnpm lint && pnpm test

# 只跑快的部分，由 .githooks/pre-commit 调用，目标 30 秒以内
pre-commit:
    cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q -m "not slow"
    cd frontend && pnpm test

# 端到端主路径
e2e:
    cd frontend && pnpm build && pnpm e2e

# 真机冒烟辅助
smoke:
    @echo "用专用小号手动走一遍受影响的流程"

# 重新生成 fixture 期望快照（M0 为空实现，M1 起使用）
fixtures-update:
    cd backend && uv run --frozen python -m gleanery.fixtures.update

# 日后 CI 只调这一条
ci: check e2e
