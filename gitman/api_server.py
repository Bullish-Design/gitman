#!/usr/bin/env python
"""FastAPI sink that writes every incoming GitHub webhook POST to the jsonl log."""

from fastapi import FastAPI, Request, Response
from gitman import ensure_gitman_dir, EVENT_LOG
import json, logging, datetime

app = FastAPI(title="Gitman Webhook Sink")
logger = logging.getLogger("gitman.api")

ensure_gitman_dir()


@app.post("/webhook")
async def sink(req: Request):
    payload = await req.body()
    EVENT_LOG.write_bytes(payload + b"\n")
    logger.info("📥 received event (%d bytes)", len(payload))
    return Response(status_code=200)


def main():
    import uvicorn, os

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("gitman.api_server:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
