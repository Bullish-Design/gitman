"""Unit tests: config defaults (no jj/git subprocess needed).

The old jj/git `--version` string parsers were removed in the pyjutsu migration: gitman no
longer probes a `jj` CLI (the engine is in-process via pyjutsu, version-asserted at import) and
`doctor` checks `pyjutsu.JJ_VERSION == pyjutsu.JJ_LIB_TARGET` instead.
"""

from __future__ import annotations

from pathlib import Path

from gitman.config import load_config


def test_config_defaults(tmp_path: Path):
    cfg = load_config(tmp_path)  # no config files present
    assert cfg.trunk is None
    assert cfg.publish.on_fail == "block"
    assert cfg.release.tag_format == "v{version}"
    assert cfg.source_path is None
    assert cfg.version.configured is False
