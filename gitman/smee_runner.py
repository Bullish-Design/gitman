#!/usr/bin/env python
"""Smee client: show/forward/send; writes every message to a JSONL log."""

from __future__ import annotations
import argparse, json, logging, signal, sys
from pathlib import Path
import requests
from rich import print as rprint
from rich.console import Console
from requests_sse import EventSource
from gitman import ensure_gitman_dir, EVENT_LOG

LOG = logging.getLogger("gitman.smee")
console = Console()
ensure_gitman_dir()  # make sure dirs exist

# ── helpers ───────────────────────────────────────────────────────


def _decode(raw: str):
    obj = json.loads(raw)
    body = json.dumps(obj["body"], separators=(",", ":"))
    hdrs = {k: str(v) for k, v in obj.items() if k not in ("query", "body", "host")}
    return hdrs, body


def _pretty(raw: str):
    _, body = _decode(raw)
    rprint("[bold yellow]⇢ Payload:[/bold yellow]")
    console.print_json(body)


def _post(dst: str, raw: str):
    hdrs, body = _decode(raw)
    try:
        resp = requests.post(dst, data=body, headers=hdrs, timeout=10)
        LOG.info("POST %s → %s", dst, resp.status_code)
    except requests.RequestException as exc:
        LOG.error("POST failed: %s", exc)


def _write_log(raw: str):
    with EVENT_LOG.open("a", encoding="utf-8") as fp:
        fp.write(raw + "\n")


def _stream(url: str):
    """Yield message events from Smee (requests-sse iterator)."""
    with EventSource(url, timeout=None) as es:
        for ev in es:
            yield ev


# ── command funcs ────────────────────────────────────────────────


def _cmd_show(a):
    LOG.info("Watching %s", a.source)
    for ev in _stream(a.source):
        if ev.type == "message":
            _pretty(ev.data)
            _write_log(ev.data)


def _cmd_forward(a):
    LOG.info("Forwarding %s → %s", a.source, a.target)
    for ev in _stream(a.source):
        if ev.type == "message":
            _post(a.target, ev.data)
            _write_log(ev.data)


def _cmd_send(a):
    LOG.info("Replaying %s → %s", a.file.name, a.source)
    for line in a.file:
        if line := line.strip():
            _post(a.source, line)
            _write_log(line)


# ── CLI ──────────────────────────────────────────────────────────


def _build() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Smee.io client (gitman)")
    p.add_argument("-v", "--verbose", action="count", default=0)
    sub = p.add_subparsers(dest="cmd", required=True)

    show = sub.add_parser("show")
    show.add_argument("source")
    show.set_defaults(fn=_cmd_show)
    fwd = sub.add_parser("forward")
    fwd.add_argument("source")
    fwd.add_argument("target")
    fwd.set_defaults(fn=_cmd_forward)
    snd = sub.add_parser("send")
    snd.add_argument("source")
    snd.add_argument("file", type=argparse.FileType("r"))
    snd.set_defaults(fn=_cmd_send)
    return p


def main():
    args = _build().parse_args()
    lvl = {0: logging.WARNING, 1: logging.INFO}.get(args.verbose, logging.DEBUG)
    logging.basicConfig(format="[%(asctime)s] %(levelname)s: %(message)s", level=lvl)
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    args.fn(args)


if __name__ == "__main__":
    main()
