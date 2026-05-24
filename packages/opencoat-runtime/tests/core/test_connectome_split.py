"""Tests for connectome split primitive."""

from __future__ import annotations

from opencoat_runtime_core.credit.connectome_split import (
    collect_pointcut_keywords,
    materialize_split,
    propose_keyword_split,
)
from opencoat_runtime_protocol import Concern, PointcutDef
from opencoat_runtime_protocol.envelopes import PointcutMatch


def test_propose_keyword_split_partitions_domain() -> None:
    concern = Concern(
        id="wide-guard",
        name="wide",
        pointcuts=[
            PointcutDef(
                id="pc",
                joinpoints=["before_tool_call"],
                match=PointcutMatch(any_keywords=["alpha", "beta", "gamma", "delta"]),
            ),
        ],
    )
    proposal = propose_keyword_split(concern)
    assert proposal is not None
    assert proposal.child_a_id == "wide-guard--a"
    assert proposal.child_b_id == "wide-guard--b"
    assert set(proposal.keywords_a) | set(proposal.keywords_b) == set(
        collect_pointcut_keywords(concern)
    )
    assert set(proposal.keywords_a).isdisjoint(set(proposal.keywords_b))


def test_materialize_split_creates_specialized_children() -> None:
    concern = Concern(
        id="wide-guard",
        name="wide",
        pointcuts=[
            PointcutDef(
                id="pc",
                joinpoints=["before_tool_call"],
                match=PointcutMatch(any_keywords=["alpha", "beta", "gamma"]),
            ),
        ],
    )
    proposal = propose_keyword_split(concern)
    assert proposal is not None
    child_a, child_b = materialize_split(proposal, concern)
    assert child_a.id == "wide-guard--a"
    assert child_b.id == "wide-guard--b"
    assert child_a.pointcuts[0].match is not None
    assert "alpha" in (child_a.pointcuts[0].match.any_keywords or [])
