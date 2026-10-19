import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env before importing modules that read os.getenv at import-time.
try:
    from dotenv import load_dotenv

    _here = Path(__file__).resolve()
    for _env in (_here.parents[2] / ".env", _here.parents[3] / ".env"):
        if _env.exists():
            load_dotenv(_env, override=False)
            break
except Exception:
    # Non-fatal in environments where dotenv isn't available.
    pass

from apis.core.database import lifespan
from apis.v1.api import api_router
from apis.core.error_logger import ErrorLogger, ErrorSeverity, ErrorCategory

# Configure comprehensive logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('compliance_ai.log'),
    ]
)

# Initialize global error logger
logger = logging.getLogger(__name__)
logger.info("=" * 80)
logger.info("Compliance AI Server Starting")
logger.info("=" * 80)

app = FastAPI(lifespan=lifespan)


def _parse_cors_origins() -> list[str]:
    """Build the CORS allow-list.

    ``CORS_ORIGINS`` (comma-separated) augments the dev defaults. We never use
    ``*`` because ``allow_credentials=True`` requires explicit origins for the
    httpOnly session cookie to be accepted by browsers.

    Dev tip: when running Vite on :5173 and FastAPI on :8052, prefer the Vite
    ``server.proxy`` for ``/api/v1`` so the browser sees one origin and cookies
    attach automatically. Otherwise both origins must be listed here.
    """
    defaults = [
        "http://localhost:8054",
        "http://127.0.0.1:8054",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    raw = os.getenv("CORS_ORIGINS", "") or ""
    extra = [o.strip() for o in raw.split(",") if o.strip()]
    # Preserve order; de-dupe while keeping first occurrence.
    seen: set[str] = set()
    result: list[str] = []
    for origin in [*defaults, *extra]:
        if origin and origin not in seen:
            seen.add(origin)
            result.append(origin)
    return result


app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

if __name__ == "__main__":
    with open("server_startup.txt", "w") as f:
        f.write("Starting server...\\n")
    try:
        # Using 0.0.0.0 to avoid localhost resolution issues
        uvicorn.run(app, host="0.0.0.0", port=8052)
    except Exception as e:
        with open("server_startup.txt", "a") as f:
            f.write(f"Server failed to start: {e}\\n")
        import traceback
        with open("server_startup.txt", "a") as f:
            traceback.print_exc(file=f)