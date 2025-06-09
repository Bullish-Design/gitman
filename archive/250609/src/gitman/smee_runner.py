#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests", "requests-sse", "rich"]
# ///

from __future__ import annotations

import argparse, json, signal, sys, logging, collections, requests
from pathlib import Path
from rich import print as rprint
from rich.console import Console
from requests_sse import (
    EventSource,
    InvalidStatusCodeError,
    InvalidContentTypeError,
)  # ← native iterator ✔
from typing import Dict, Tuple

LOG = logging.getLogger("smee")
console = Console()


# ───────────────────────── helpers ──────────────────────────
def decode(raw: str) -> Tuple[Dict[str, str], str]:
    """Return (headers, body_json_str) exactly like original pysmee."""
    obj = json.loads(raw, object_pairs_hook=collections.OrderedDict)
    body = json.dumps(obj["body"], separators=(",", ":"))
    hdrs = {k: str(v) for k, v in obj.items() if k not in ("query", "body", "host")}
    return hdrs, body


def pretty(raw: str) -> None:
    _, body = decode(raw)
    rprint("[bold yellow]⇢ Payload:[/bold yellow]")
    console.print_json(body)


def post(target: str, raw: str) -> None:
    hdrs, body = decode(raw)
    try:
        resp = requests.post(target, data=body, headers=hdrs, timeout=10)
        LOG.info("POST %s → %s", target, resp.status_code)
    except requests.RequestException as exc:
        LOG.error("POST failed: %s", exc)


def stream(url: str):
    """Yield *all* events from Smee using requests-sse’s iterator interface."""
    with EventSource(
        url, timeout=None
    ) as es:  # iterator per docs :contentReference[oaicite:0]{index=0}
        for ev in es:  # Event has .event / .data
            yield ev


# ───────────────────────── command handlers ─────────────────
def cmd_show(a):
    LOG.info("Watching %s", a.source)
    for ev in stream(a.source):
        if ev.type == "message":
            pretty(ev.data)
        else:
            LOG.debug("non-message event: %s", ev.event)
        if a.save:
            print(ev.data, file=a.save)


def cmd_forward(a):
    LOG.info("Forwarding %s → %s", a.source, a.target)
    try:
        for ev in stream(a.source):
            print(f"Event: {ev}")

            if ev.type == "message":
                post(a.target, ev.data)
            if a.save:
                print(ev.data, file=a.save)
    except (InvalidStatusCodeError, InvalidContentTypeError) as exc:
        LOG.error("Error while streaming: %s", exc)
        pass
    except requests.RequestException as exc:
        LOG.error("POST failed: %s", exc)
        pass
    # except:
    #    print(f"[red]Unexpected error: {sys.exc_info()[0]}[/red]")
    #    pass


def cmd_send(a):
    LOG.info("Re-sending %s → %s", a.file.name, a.source)
    for line in a.file:
        if line := line.strip():
            post(a.source, line)


# ───────────────────────── CLI ──────────────────────────────
def build_parser():
    p = argparse.ArgumentParser(description="Tiny smee.io client using requests-sse")
    p.add_argument("-v", "--verbose", action="count", default=0)
    sub = p.add_subparsers(dest="cmd", required=True)

    show = sub.add_parser("show", help="Display events")
    show.add_argument("source")
    show.add_argument("--save", type=argparse.FileType("a"))
    show.set_defaults(fn=cmd_show)

    fwd = sub.add_parser("forward", help="Forward events to HTTP endpoint")
    fwd.add_argument("source")
    fwd.add_argument("target")
    fwd.add_argument("--save", type=argparse.FileType("a"))
    fwd.set_defaults(fn=cmd_forward)

    snd = sub.add_parser("send", help="Replay saved events")
    snd.add_argument("source")
    snd.add_argument("file", type=argparse.FileType("r"))
    snd.set_defaults(fn=cmd_send)
    return p


# ───────────────────────── entry-point ──────────────────────
def main():
    args = build_parser().parse_args()
    lvl = {0: logging.WARNING, 1: logging.INFO}.get(args.verbose, logging.DEBUG)
    logging.basicConfig(format="[%(asctime)s] %(levelname)s: %(message)s", level=lvl)

    signal.signal(signal.SIGINT, lambda *_: (LOG.info("Stopping…"), sys.exit(0)))
    args.fn(args)


if __name__ == "__main__":
    main()
