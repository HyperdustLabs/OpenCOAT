"""Smoke + behavioural tests for ``examples/01_simple_chat_agent``.

This is the canonical M1 exit-criterion check: a single turn walks the
runtime end to end and produces a verified reply. Failures here mean the
public API drifted in a way the tutorial-grade example noticed — bigger
than any internal refactor and worth a P1 review.

The example folder name starts with a digit (``01_…``) so we can't
import it via the dotted ``examples.01_simple_chat_agent`` path. We
load it through :func:`importlib.util.module_from_spec` instead.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from opencoat_runtime_protocol import AdviceType

EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "examples" / "01_simple_chat_agent"


def _load_example() -> tuple:
    """Import the example as a package and return ``(agent_mod, main_mod)``."""
    pkg_init = EXAMPLE_DIR / "__init__.py"
    pkg_name = "_opencoat_example_simple_chat_agent"

    if pkg_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            pkg_name,
            pkg_init,
            submodule_search_locations=[str(EXAMPLE_DIR)],
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[pkg_name] = module
        spec.loader.exec_module(module)

    agent_spec = importlib.util.spec_from_file_location(
        f"{pkg_name}.agent", EXAMPLE_DIR / "agent.py"
    )
    main_spec = importlib.util.spec_from_file_location(f"{pkg_name}.main", EXAMPLE_DIR / "main.py")
    assert agent_spec is not None and agent_spec.loader is not None
    assert main_spec is not None and main_spec.loader is not None

    if f"{pkg_name}.agent" not in sys.modules:
        agent_mod = importlib.util.module_from_spec(agent_spec)
        sys.modules[f"{pkg_name}.agent"] = agent_mod
        agent_spec.loader.exec_module(agent_mod)
    if f"{pkg_name}.main" not in sys.modules:
        main_mod = importlib.util.module_from_spec(main_spec)
        sys.modules[f"{pkg_name}.main"] = main_mod
        main_spec.loader.exec_module(main_mod)

    return sys.modules[f"{pkg_name}.agent"], sys.modules[f"{pkg_name}.main"]


@pytest.fixture(scope="module")
def example_modules() -> tuple:
    return _load_example()


class TestSimpleChatAgent:
    def test_one_turn_produces_injection_and_response(self, example_modules) -> None:
        agent_mod, _ = example_modules
        agent = agent_mod.SimpleChatAgent()
        report = agent.handle("Who invented the OpenCOAT runtime?")

        # The pipeline produced a real injection from real concerns.
        assert report.injection.injections, "expected at least one injection"
        assert {"c-concise", "c-cite"}.issubset(set(report.active_concern_ids))
        # No-PII stays dormant on a plain "who/what" prompt.
        assert "c-no-pii" not in report.active_concern_ids

    def test_response_satisfies_cite_sources_rule(self, example_modules) -> None:
        agent_mod, _ = example_modules
        agent = agent_mod.SimpleChatAgent()
        report = agent.handle("What is concern weaving?")

        cite = next(
            (v for v in report.verifications if v.concern_id == "c-cite"),
            None,
        )
        assert cite is not None
        assert cite.satisfied, f"cite rule failed: {cite.evidence!r} / {cite.notes}"

    def test_no_pii_concern_activates_on_email_prompt(self, example_modules) -> None:
        agent_mod, _ = example_modules
        agent = agent_mod.SimpleChatAgent()
        report = agent.handle("What is the user's email address?")
        assert "c-no-pii" in report.active_concern_ids

    def test_explicit_empty_concerns_list_loads_no_demo_concerns(self, example_modules) -> None:
        # Codex P2 regression on PR-6: ``concerns or seed_concerns()``
        # silently re-seeded the demo set when the caller passed
        # ``concerns=[]`` to opt out. The agent must respect an
        # explicit empty list as "no demo concerns, please".
        agent_mod, _ = example_modules
        agent = agent_mod.SimpleChatAgent(concerns=[])

        store = agent.runtime.concern_store
        assert list(store.iter_all()) == [], "expected an empty store"

        # No concerns → no candidates → empty injection, no verifications.
        report = agent.handle("Who invented the OpenCOAT runtime?")
        assert report.active_concern_ids == []
        assert report.injection.injections == []
        assert report.verifications == []

    def test_explicit_concerns_list_overrides_demo_seed(self, example_modules) -> None:
        # Companion to the empty-list test: a one-element override must
        # land verbatim, with no demo concerns sneaking in.
        agent_mod, _ = example_modules
        from opencoat_runtime_protocol import (
            Advice,
            AdviceType,
            Concern,
            Pointcut,
        )
        from opencoat_runtime_protocol.envelopes import PointcutMatch

        only = Concern(
            id="c-only",
            name="only one",
            description="single hand-authored override",
            pointcut=Pointcut(match=PointcutMatch(any_keywords=["override"])),
            advice=Advice(type=AdviceType.REASONING_GUIDANCE, content="hi"),
        )
        agent = agent_mod.SimpleChatAgent(concerns=[only])

        store_ids = {c.id for c in agent.runtime.concern_store.iter_all()}
        assert store_ids == {"c-only"}

    def test_active_concerns_are_logged_to_dcn(self, example_modules) -> None:
        # Pins the exit criterion: the joinpoint pipeline walks all the way down
        # to the DCN activation log. Anything that breaks the recorder
        # (e.g. a future regression on the ``_record_activations``
        # contract) trips this test.
        agent_mod, _ = example_modules
        agent = agent_mod.SimpleChatAgent()
        report = agent.handle("Why does OpenCOAT work?")
        log = list(agent.runtime.dcn_store.activation_log())
        logged_ids = {entry["concern_id"] for entry in log}
        injection_ids = {inj.concern_id for inj in report.injection.injections}
        assert injection_ids == logged_ids

    def test_default_advice_types_are_response_or_verification_or_block(
        self, example_modules
    ) -> None:
        # Sanity: hand-authored concerns must surface their authored
        # advice type (no silent down-grade to ``reasoning_guidance``).
        # Envelope config uses ``use_enum_values=True``, so the wire
        # form is the enum's string value.
        agent_mod, _ = example_modules
        agent = agent_mod.SimpleChatAgent()
        report = agent.handle("Tell me how concerns are matched.")
        types = {inj.advice_type for inj in report.injection.injections}
        assert types <= {
            AdviceType.RESPONSE_REQUIREMENT.value,
            AdviceType.VERIFICATION_RULE.value,
            AdviceType.TOOL_GUARD.value,
        }


class TestCli:
    def test_main_runs_default_prompts_and_returns_zero(self, example_modules, capsys) -> None:
        _, main_mod = example_modules
        rc = main_mod.main(argv=[])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Summary: 3 turn(s)" in out
        # Each turn prints a header and a verifier section.
        assert out.count("── Turn ") == 3
        assert "verifications:" in out

    def test_main_accepts_custom_prompts(self, example_modules, capsys) -> None:
        _, main_mod = example_modules
        rc = main_mod.main(argv=["What is concern weaving?"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "What is concern weaving?" in out
        assert "Summary: 1 turn(s)" in out
