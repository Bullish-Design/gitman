"""Suite-wide pytest configuration.

The suite runs in parallel. Every test builds its own repo under `tmp_path`, and gitman's
repo lock is keyed per repo root, so workers never contend. `-n auto` is in `addopts`
(pyproject.toml), which makes the parallel path the default for a bare `pytest` and for the
`gitman:test` task alike. Pass `-n0` to run serially — use it to debug one test, or with
`--pdb`.
"""

from __future__ import annotations

import os

# Measured on an 8-core machine at 475 tests: 8 workers ran the suite in 32 s, 12 in 22 s,
# 24 in 22 s, 32 in 25 s. The work is partly I/O bound (jj writes a repo per test), so
# oversubscribing cores pays until worker start-up dominates.
_WORKERS_PER_CORE = 1.5
_MAX_WORKERS = 24


def pytest_xdist_auto_num_workers(config) -> int:
    """Give `-n auto` a worker count tuned for this suite instead of one per core."""
    try:
        cores = len(os.sched_getaffinity(0))
    except AttributeError:  # not Linux
        cores = os.cpu_count() or 1
    return max(1, min(_MAX_WORKERS, int(cores * _WORKERS_PER_CORE)))
