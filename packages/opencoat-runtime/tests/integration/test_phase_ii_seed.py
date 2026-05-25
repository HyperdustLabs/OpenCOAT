"""Bootstrap concern extraction for Phase II (no coding demo presets)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore  # noqa: E402

from experiments.man_paper.phase_ii_seed import (  # noqa: E402
    H0_CONSERVED_REFLEX_ID,
    MAN_IDENTITY_PROMPT,
    seed_h0_graph,
)
from experiments.man_paper.phase_ii_stub import PhaseIIStubLLM  # noqa: E402


def test_seed_h0_graph_stub() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    cortex = seed_h0_graph(PhaseIIStubLLM(), store=store, dcn=dcn)
    assert cortex.id
    assert cortex.reflex is False
    assert cortex.pointcut is not None
    assert cortex.pointcut.joinpoints == ["before_response"]
    assert cortex.pointcut.match is None
    assert MAN_IDENTITY_PROMPT.lower() in (cortex.description or "").lower()
    assert cortex.source is not None
    assert cortex.source.origin == "intent_alignment"
    reflex = store.get(H0_CONSERVED_REFLEX_ID)
    assert reflex is not None
    assert reflex.reflex is True
    assert reflex.neuron_type == "inhibitory"
    assert len(list(store.iter_all())) == 2
    assert dcn.edge_count() == 0
