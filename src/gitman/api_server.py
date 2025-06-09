#!/usr/bin/env python
"""FastAPI sink that writes every incoming GitHub webhook POST to the jsonl log."""

from fastapi import FastAPI, Request, Response
from gitman import ensure_gitman_dir, EVENT_LOG, GITMAN_DIR
import json, logging, datetime, os

app = FastAPI(title="Gitman Webhook Sink")
logger = logging.getLogger("gitman.api")

ensure_gitman_dir()

LOG_DIR = GITMAN_DIR / "logs"


@app.post("/webhook")
async def sink(req: Request):
    payload = await req.body()
    # print(f"\n📥 received event ({len(payload)} bytes)")
    # print(
    #    f"{json.dumps(json.loads(payload.decode('utf-8')), indent=2, ensure_ascii=False)}"
    # )
    EVENT_LOG.write_bytes(payload + b"\n")
    logger.info("📥 received event (%d bytes)", len(payload))

    event = req.headers.get("X-GitHub-Event", "unknown")
    action = json.loads(payload).get("action", "unknown")
    key = f"{event}_{action}".replace(":", "_")
    print(f"    📥 Logging event: {key} ({len(payload)} bytes)")
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(f"{LOG_DIR}/{key}.jsonl", "a") as f:
        f.write(payload.decode() + "\n")
    return Response(status_code=200)


def main():
    import uvicorn, os

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        "gitman.api_server:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        reload_dirs=["src/gitman"],
    )


if __name__ == "__main__":
    main()
