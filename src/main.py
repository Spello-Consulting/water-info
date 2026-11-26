"""water-info entry point.

Parses ``--config`` / ``--homedir``, loads and validates configuration, wires
logging, and runs the FastAPI app under uvicorn with a single worker (only the
poller writes to SQLite; one worker keeps that a single writer — see design.md).
"""
from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from app import create_app
from config import AppConfig, build_config_manager, build_logger

# Maximum time uvicorn waits for in-flight connections to close during a graceful
# shutdown before cancelling them. Without this bound, an open /ws dashboard WebSocket
# keeps uvicorn waiting indefinitely on a single SIGTERM (the deploy controller sends
# SIGTERM once, then SIGKILLs ~90s later), so the process appears to hang on stop.
WEB_SERVER_GRACEFUL_SHUTDOWN_TIMEOUT = 5


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Water Information Display web application")
    parser.add_argument("--config", default="config.yaml", help="Path to the YAML config file (default: config.yaml)")
    # --homedir is consumed by scripts/launch.sh (which chdirs before launch);
    # accepted here so the arg doesn't cause an error.
    parser.add_argument("--homedir", default=None, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    if args.homedir:
        os.chdir(args.homedir)

    try:
        config_mgr = build_config_manager(args.config)
    except RuntimeError as exc:
        print(f"[water-info] Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    logger = build_logger(config_mgr)
    app_config = AppConfig(config_mgr)
    app = create_app(app_config, logger)

    logger.log_message(f"water-info starting on {app_config.host}:{app_config.port}", "summary")
    # Single worker only — keeps the poller the sole SQLite writer.
    uvicorn.run(
        app,
        host=app_config.host,
        port=app_config.port,
        workers=1,
        log_level="info",
        timeout_graceful_shutdown=WEB_SERVER_GRACEFUL_SHUTDOWN_TIMEOUT,
    )


if __name__ == "__main__":
    main()
