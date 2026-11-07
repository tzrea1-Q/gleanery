import argparse
import asyncio
from pathlib import Path

import uvicorn
from pydantic_ai import models

from tests.e2e.app_factory import build_e2e_deps, create_e2e_app
from tests.e2e.seed import seed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    models.ALLOW_MODEL_REQUESTS = False
    asyncio.run(seed(args.data_dir))
    deps = build_e2e_deps(args.data_dir, args.port, args.token)
    uvicorn.run(
        create_e2e_app(deps),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        timeout_graceful_shutdown=3,
    )


if __name__ == "__main__":
    main()
