"""Entry point for the voicebox backend.

Imports the configured FastAPI app and provides a ``python -m backend.main``
entry point for development.
"""

import argparse
import os

import uvicorn

from .app import app  # noqa: F401 -- re-export for uvicorn "backend.main:app"
from . import config, database

# Default request body limit: 256 MB. Uvicorn's built-in default is 16 MB, which
# clips voicebox.transcribe / voicebox.analyze_sample audio_base64 uploads
# (those tools allow up to 200 MB binary). Override with VOICEBOX_MAX_BODY_BYTES.
DEFAULT_MAX_BODY_BYTES = 256 * 1024 * 1024

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="voicebox backend server")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (use 0.0.0.0 for remote access)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Data directory for database, profiles, and generated audio",
    )
    parser.add_argument(
        "--max-body-size",
        type=int,
        default=None,
        help="Max request body size in bytes (default 268435456 = 256 MB). "
        "Overrides VOICEBOX_MAX_BODY_BYTES env var.",
    )
    args = parser.parse_args()

    if args.data_dir:
        config.set_data_dir(args.data_dir)

    database.init_db()

    # Resolve body size cap: CLI flag > env > default 256 MB.
    if args.max_body_size is not None:
        max_body = args.max_body_size
    else:
        env_val = os.environ.get("VOICEBOX_MAX_BODY_BYTES")
        max_body = int(env_val) if env_val else DEFAULT_MAX_BODY_BYTES

    # uvicorn 0.42 removed client_max_size; the request body cap is enforced by
    # the underlying h11 HTTP parser via h11_max_incomplete_event_size.
    # We raise that from its default (~16 MB) to support voicebox.transcribe's
    # 200 MB audio uploads (+33% base64 overhead). For full reliability with
    # multi-MB bodies on the wire, the upstream proxy should also forward the
    # Content-Length header so h11 can pre-size its buffer.
    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=False,
        h11_max_incomplete_event_size=max_body,
    )
