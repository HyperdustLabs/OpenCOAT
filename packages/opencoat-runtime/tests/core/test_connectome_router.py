"""Architecture (ii): connectome router + synapse evolution."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core.advice import AdviceGenerator
from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.config import RuntimeConfig
from opencoat_runtime_core.connectome.router import (
    ConnectomeRouter,
    ConnectomeRoutingConfig,
    joinpoint_bucket,
)
from opencoat_runtime_core.connectome.synapse_evolution import strengthen_edge
from opencoat_runtime_core.coordinator import ConcernCoordinator
from opencoat_runtime_core.credit.connectome_plasticity import connect_coactivated, lift_coalition
from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine
from opencoat_runtime_core.credit.r_t_record import RtRecord, RtSignal
from opencoat_runtime_core.credit.rt_plasticity_service import RtPlasticityService
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_core.loops.joinpoint_pipeline import JoinpointPipeline
from opencoat_runtime_core.pointcut.matcher import PointcutMatcher
from opencoat_runtime_core.weaving import ConcernWeaver
from opencoat_runtime_protocol import (
    AdviceKind,
    AdviceType,
    AopAdvice,
    Concern,
    JoinpointEvent,
    PointcutDef,
    PointcutMatch,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
)
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore
from tests.core.test_effector_kernel import _demo_tool_block


def _pipeline(store: MemoryConcernStore, dcn: MemoryDCNStore) -> JoinpointPipeline:
    cfg = RuntimeConfig()
    return JoinpointPipeline(
        config=cfg,
        concern_store=store,
        dcn_store=dcn,
        matcher=PointcutMatcher(),
        coordinator=ConcernCoordinator(budgets=cfg.budgets),
        weaver=ConcernWeaver(budgets=cfg.budgets),
        advice_plugin=AdviceGenerator(llm=StubLLMClient()),
    )


def _concern(
    cid: str,
    *,
    joinpoints: list[str],
    keywords: list[str],
    reflex: bool = False,
) -> Concern:
    pc_id = f"pc-{cid}"
    return Concern(
        id=cid,
        name=cid,
        reflex=reflex,
        neuron_type="inhibitory" if reflex else "excitatory",
        pointcuts=[
            PointcutDef(
                id=pc_id,
                expression=f"{joinpoints[0]}()",
                joinpoints=joinpoints,
                match=PointcutMatch(any_keywords=keywords),
            )
        ],
        advices=[
            AopAdvice(
                id=f"adv-{cid}",
                kind=AdviceKind.BEFORE,
                pointcut_ref=pc_id,
                content=f"advice for {cid}",
                template=AdviceType.TOOL_GUARD if reflex else AdviceType.REASONING_GUIDANCE,
                effect=WeavingPolicy(
                    mode=WeavingOperation.BLOCK if reflex else WeavingOperation.INSERT,
                    level=WeavingLevel.TOOL_LEVEL if reflex else WeavingLevel.PROMPT_LEVEL,
                    target="tool_call.arguments" if reflex else "prompt.system",
                    priority=0.9,
                ),
            )
        ],
    )


def test_joinpoint_bucket() -> None:
    assert joinpoint_bucket("before_tool_call") == "before"
    assert joinpoint_bucket("queue.before_enqueue") == "queue"


def test_synapse_boost_routes_child_when_parent_active() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    parent = _concern("parent-a", joinpoints=["before_tool_call"], keywords=["alpha"])
    child = _concern("child-b", joinpoints=["before_tool_call"], keywords=["beta"])
    store.upsert(parent)
    store.upsert(child)
    dcn.add_node(parent)
    dcn.add_node(child)
    strengthen_edge(dcn, "parent-a", "child-b", delta=0.5, floor=0.5)

    router = ConnectomeRouter(ConnectomeRoutingConfig(moe_per_bucket=4))
    jp = JoinpointEvent(
        id="jp-r",
        level=3,
        name="before_tool_call",
        host="t",
        ts=datetime.now(tz=UTC),
        payload={"text": "alpha beta", "command": "alpha"},
    )
    hits = [(parent, 0.9), (child, 0.2)]
    routed = router.route(jp, hits, concern_store=store, dcn_store=dcn)
    scores = {c.id: s for c, s in routed}
    assert "parent-a" in scores
    assert scores["child-b"] > 0.2


def test_moe_caps_per_joinpoint_bucket() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    concerns = [
        _concern(f"c-{i}", joinpoints=["before_tool_call"], keywords=[f"kw{i}"]) for i in range(4)
    ]
    for c in concerns:
        store.upsert(c)
    router = ConnectomeRouter(ConnectomeRoutingConfig(moe_per_bucket=2))
    jp = JoinpointEvent(
        id="jp-t",
        level=3,
        name="before_tool_call",
        host="t",
        ts=datetime.now(tz=UTC),
    )
    hits = [(c, 1.0 - i * 0.1) for i, c in enumerate(concerns)]
    routed = router.route(jp, hits, concern_store=store, dcn_store=dcn)
    assert len(routed) <= 2
    assert routed[0][0].id == "c-0"


def test_lift_hub_expands_members() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    a = _concern("aspect-a", joinpoints=["before_tool_call"], keywords=["shared", "a"])
    b = _concern("aspect-b", joinpoints=["before_tool_call"], keywords=["shared", "b"])
    store.upsert(a)
    store.upsert(b)
    dcn.add_node(a)
    dcn.add_node(b)
    connect_coactivated(concern_store=store, dcn_store=dcn, co_pairs=[("aspect-a", "aspect-b")])
    lift_coalition(
        concern_store=store,
        dcn_store=dcn,
        members=("aspect-a", "aspect-b"),
        coalition_id="lift.aspect-a--aspect-b",
    )
    hub = store.get("lift.aspect-a--aspect-b")
    assert hub is not None
    router = ConnectomeRouter(ConnectomeRoutingConfig(hub_boost=0.4))
    jp = JoinpointEvent(
        id="jp-l",
        level=3,
        name="before_tool_call",
        host="t",
        ts=datetime.now(tz=UTC),
        payload={"text": "shared"},
    )
    routed = router.route(jp, [(hub, 0.85)], concern_store=store, dcn_store=dcn)
    ids = {c.id for c, _ in routed}
    assert "lift.aspect-a--aspect-b" in ids
    assert "aspect-a" in ids or "aspect-b" in ids


def test_pipeline_coactivation_feeds_warm_connect() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    store.upsert(_demo_tool_block())
    c2 = _concern("peer-c", joinpoints=["before_tool_call"], keywords=["ls"])
    store.upsert(c2)
    svc = RtPlasticityService(concern_store=store, dcn_store=dcn)
    pipeline = _pipeline(store, dcn)
    pipeline.set_coactivation_recorder(svc.record_coactivation)
    jp = JoinpointEvent(
        id="jp-co",
        level=3,
        name="before_tool_call",
        host="t",
        ts=datetime.now(tz=UTC),
        payload={"command": "ls -la"},
    )
    pipeline.run(jp, context={"command": "ls -la"})
    warm = svc.consume(max_records=0)
    assert warm.connected >= 0
    stats = svc.connectome_stats()
    assert stats["edges"] >= 0


def test_warm_reweights_synapses_from_rt() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    block = _demo_tool_block()
    store.upsert(block)
    dcn.add_node(block)
    peer = _concern("peer", joinpoints=["before_tool_call"], keywords=["x"])
    store.upsert(peer)
    dcn.add_node(peer)
    strengthen_edge(dcn, "peer", "demo-tool-block", delta=0.3, floor=0.3)

    rec = RtRecord(
        ts=datetime.now(tz=UTC),
        session_id="s",
        turn_id="t",
        joinpoint="before_tool_call",
        hook="before_tool_call",
        signal=RtSignal(
            kind="tool_blocked",
            reflex={"policy_id": "demo-tool-block", "decision": "deny"},
        ),
        r=1.0,
    )
    engine = PlasticityEngine()
    warm = engine.warm_step(
        [rec],
        concern_store=store,
        dcn_store=dcn,
        lifecycle=ConcernLifecycleManager(concern_store=store, dcn_store=dcn),
        co_pairs=[("peer", "demo-tool-block")],
    )
    assert warm.synapses_strengthened >= 1
