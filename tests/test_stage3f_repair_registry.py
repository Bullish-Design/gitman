"""Issue 44 stage 3f — the registry dispatches the repair (guide §3.13).

`anomalies.REGISTRY` names which intent repairs each anomaly kind, but nothing read that field —
it was an assertion about the world, not a wiring into it. `repairs.REPAIRS` is the table
`do_reconcile` now dispatches through, in `repairs.REPAIRS_ORDER`, guarded at import time by a
two-way assertion against `REGISTRY`. This file tests the table itself (the assertion bites, the
order is declared and pins ref-healing first) — the repair *behaviour* is covered by the stage 3d
and 3e suites, unchanged.
"""

from __future__ import annotations

import pytest

from gitman.anomalies import REGISTRY, AnomalyKind
from gitman.repairs import REPAIRS, REPAIRS_ORDER, assert_registry_agrees


def test_registry_and_repairs_agree_both_ways():
    """Every `repair="repair"` row has a callable, and every callable's row says so."""
    for slug, kind in REGISTRY.items():
        if kind.repair == "repair":
            assert slug in REPAIRS, f"{slug}: REGISTRY wants reconcile but REPAIRS has no callable"
    for slug in REPAIRS:
        assert REGISTRY[slug].repair == "repair", f"{slug}: REPAIRS has a callable REGISTRY doesn't ask for"


def test_assertion_bites_on_a_kind_registry_says_reconcile_repairs_but_repairs_lacks():
    """The mechanism itself: register a bogus kind with `repair="repair"` and no matching
    `repairs` entry — this is exactly what a forgotten callable looks like, and it must fail
    the assertion `repairs.py` runs at import time (an import error), not livelock a recovery
    verb at runtime."""
    bogus_registry = {
        "bogus-kind": AnomalyKind(tier="lane", repair="repair", blocks=frozenset()),
    }
    with pytest.raises(AssertionError, match="bogus-kind"):
        assert_registry_agrees(bogus_registry, REPAIRS)


def test_assertion_bites_the_other_direction_too():
    """A `repairs` entry whose registry row does NOT say `repair="repair"` is just as wrong —
    a callable nothing declares itself as needing."""
    bogus_repairs = dict(REPAIRS)
    bogus_repairs["lane-non-linear"] = REPAIRS["stray-change"]  # REGISTRY says repair=None here
    with pytest.raises(AssertionError, match="lane-non-linear"):
        assert_registry_agrees(REGISTRY, bogus_repairs)


def test_assertion_passes_on_the_real_tables():
    assert_registry_agrees(REGISTRY, REPAIRS)  # does not raise


# --- the repair order is declared once, and pins colocated-ref healing first ------------


def test_repairs_order_names_every_repairs_key_exactly_once():
    assert set(REPAIRS_ORDER) == set(REPAIRS)
    assert len(REPAIRS_ORDER) == len(set(REPAIRS_ORDER))


def test_repairs_order_heals_colocated_refs_first():
    """Trap 2 (guide §3.13.2): colocated-ref healing must run before every other repair, since the
    import it may do can bring git-only history — trunk included — into view. All three
    ref-repairing kinds (stage 4c split `ref-mismatched` by direction, adding `ref-lagging`) sit
    ahead of every other kind in the declared order."""
    ref_kinds = {"trunk-conflicted", "ref-mismatched", "ref-lagging"}
    first_three = set(REPAIRS_ORDER[:3])
    assert first_three == ref_kinds, REPAIRS_ORDER
    assert REPAIRS_ORDER.index("lane-conflicted") > 2
    assert REPAIRS_ORDER.index("stray-change") > REPAIRS_ORDER.index("lane-conflicted")
    assert REPAIRS_ORDER.index("lane-divergent") == len(REPAIRS_ORDER) - 1


def test_repairs_order_is_not_anomaly_order():
    """The two orders exist for different reasons and must not be silently made to alias each
    other — `ANOMALY_ORDER` is a fixed prose order (trunk-diverged before lane-conflicted), which
    would run repairs in the wrong sequence if ever substituted in by mistake."""
    from gitman.anomalies import ANOMALY_ORDER

    assert REPAIRS_ORDER != tuple(k for k in ANOMALY_ORDER if k in REPAIRS)


# --- do_reconcile dispatches through the table — no per-shape branch left ----------------


def test_do_reconcile_dispatches_through_the_table():
    """Structural pin: `do_reconcile`'s repair phase is one loop over `REPAIRS_ORDER` calling
    `REPAIRS[kind]`, not a hand-maintained branch per kind."""
    import inspect

    import gitman.repair as repair_mod

    src = inspect.getsource(repair_mod.do_repair)
    assert "REPAIRS_ORDER" in src
    assert "REPAIRS[" in src
    assert "for kind in REPAIRS_ORDER" in src
