"""Apply drained ``κ_s`` ledger to DCN edge weights (morphogenetic §3 edge credit)."""

from __future__ import annotations

from contextlib import suppress

from opencoat_runtime_core.connectome.synapse_evolution import strengthen_edge, weaken_edge
from opencoat_runtime_core.ports import ConcernStore, DCNStore


def apply_synapse_kappa_ledger(
    ledger: list[tuple[str, str, float]],
    *,
    concern_store: ConcernStore,
    dcn_store: DCNStore,
    step_scale: float = 0.05,
) -> dict[str, int]:
    strengthened = 0
    weakened = 0
    skipped = 0
    for src, dst, kappa in ledger:
        if not src or not dst or src == dst:
            skipped += 1
            continue
        for cid in (src, dst):
            c = concern_store.get(cid)
            if c is not None:
                with suppress(Exception):
                    dcn_store.add_node(c)
        delta = min(0.2, abs(kappa) * step_scale)
        if kappa > 0:
            if strengthen_edge(dcn_store, src, dst, delta=delta):
                strengthened += 1
        elif kappa < 0:
            if weaken_edge(dcn_store, src, dst, delta=delta):
                weakened += 1
        else:
            skipped += 1
    return {
        "synapses_strengthened": strengthened,
        "synapses_weakened": weakened,
        "synapses_skipped": skipped,
    }


__all__ = ["apply_synapse_kappa_ledger"]
