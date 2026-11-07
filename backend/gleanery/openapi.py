"""导出 OpenAPI，供前端 openapi-typescript 生成类型：`python -m gleanery.openapi <输出路径>`。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI

from gleanery import __version__
from gleanery.api.routers import ROUTERS


def build_schema() -> dict:
    app = FastAPI(title="Gleanery", version=__version__)
    for router in ROUTERS:
        app.include_router(router)
    return app.openapi()


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    out.write_text(
        json.dumps(build_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
