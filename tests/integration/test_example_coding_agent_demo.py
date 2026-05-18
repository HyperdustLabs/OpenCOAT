"""Smoke + behavioural tests for ``examples/02_coding_agent_demo``.

This is the canonical M2 exit-criterion check: the same end-to-end
joinpoint pipeline as the M1 example, plus

* env-driven provider selection (stub fallback for hermetic CI),
* a real :meth:`LLMClient.chat` call in the response path (against
  the stub here — real providers light up the same code path), and
* :class:`ConcernLifecycleManager.reinforce` on every activation.

All tests run against the deterministic stub LLM by way of a
forced ``OPENCOAT_DEMO_PROVIDER=stub`` env. CI never sets any provider
keys, but pinning the override here means a developer's local
``OPENAI_API_KEY`` doesn't accidentally turn the smoke test into a
network test.

The example folder name starts with a digit, so we load it via
``importlib.util.module_from_spec`` — same pattern as the
``01_simple_chat_agent`` smoke test.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_protocol import AdviceType

EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "examples" / "02_coding_agent_demo"
PKG_NAME = "_opencoat_example_coding_agent_demo"


# ---------------------------------------------------------------------------
# Loader (mirrors test_example_simple_chat_agent._load_example)
# ---------------------------------------------------------------------------


def _load_example() -> tuple:
    """Import the example as a package and return ``(agent, main, llm)``."""
    pkg_init = EXAMPLE_DIR / "__init__.py"

    if PKG_NAME not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            PKG_NAME,
            pkg_init,
            submodule_search_locations=[str(EXAMPLE_DIR)],
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[PKG_NAME] = module
        spec.loader.exec_module(module)

    submodules: dict[str, object] = {}
    for name in ("agent", "main", "llm", "concerns"):
        full = f"{PKG_NAME}.{name}"
        if full not in sys.modules:
            sub_spec = importlib.util.spec_from_file_location(full, EXAMPLE_DIR / f"{name}.py")
            assert sub_spec is not None and sub_spec.loader is not None
            mod = importlib.util.module_from_spec(sub_spec)
            sys.modules[full] = mod
            sub_spec.loader.exec_module(mod)
        submodules[name] = sys.modules[full]
    return (
        submodules["agent"],
        submodules["main"],
        submodules["llm"],
        submodules["concerns"],
    )


@pytest.fixture(scope="module")
def example_modules() -> tuple:
    return _load_example()


@pytest.fixture(autouse=True)
def _force_stub_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the demo to the stub regardless of the developer's env.

    Without this, a developer who exports ``OPENAI_API_KEY`` for
    their day job would silently start hitting the real OpenAI API
    when running ``pytest`` locally — both slow and a genuine
    privacy / cost foot-gun. CI doesn't set the var so it's a no-op
    there.
    """
    monkeypatch.setenv("OPENCOAT_DEMO_PROVIDER", "stub")
    # Also blank out any inherited keys so the auto-detect ladder
    # has nothing to grab onto if a future refactor stops honouring
    # the explicit override first.
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Provider selection ladder
# ---------------------------------------------------------------------------


class TestSelectLLM:
    def test_default_with_no_env_picks_stub(self, example_modules) -> None:
        _, _, llm_mod, _ = example_modules
        client, label = llm_mod.select_llm(env={})
        assert isinstance(client, StubLLMClient)
        assert label == "stub"

    def test_explicit_stub_override(self, example_modules) -> None:
        _, _, llm_mod, _ = example_modules
        client, label = llm_mod.select_llm("stub", env={})
        assert isinstance(client, StubLLMClient)
        assert label == "stub"

    def test_unknown_provider_raises(self, example_modules) -> None:
        _, _, llm_mod, _ = example_modules
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            llm_mod.select_llm("not-a-provider", env={})

    def test_explicit_param_beats_env(self, example_modules) -> None:
        # An explicit ``provider=`` argument wins even when the env
        # would name a different provider. We use ``stub`` as the
        # winner here because we don't want the test to actually
        # construct a real OpenAI client (would need credentials).
        _, _, llm_mod, _ = example_modules
        client, label = llm_mod.select_llm(
            "stub",
            env={"OPENCOAT_DEMO_PROVIDER": "openai", "OPENAI_API_KEY": "sk-fake"},
        )
        assert isinstance(client, StubLLMClient)
        assert label == "stub"

    def test_env_var_drives_choice(self, example_modules) -> None:
        # ``OPENCOAT_DEMO_PROVIDER=stub`` resolves to the stub even when
        # an OpenAI key is also set — the explicit env var wins
        # over the auto-detect ladder.
        _, _, llm_mod, _ = example_modules
        client, _label = llm_mod.select_llm(
            env={"OPENCOAT_DEMO_PROVIDER": "stub", "OPENAI_API_KEY": "sk-fake"}
        )
        assert isinstance(client, StubLLMClient)

    def test_stub_default_chat_advertises_provider_swap(self, example_modules) -> None:
        # The stub's canned reply must mention the env vars so a
        # developer running ``uv run python -m … main`` without
        # creds knows how to flip into real-LLM mode.
        _, _, llm_mod, _ = example_modules
        client, _ = llm_mod.select_llm(env={})
        reply = client.chat(messages=[{"role": "user", "content": "hi"}])
        assert "OPENAI_API_KEY" in reply
        # The cite-docs verifier rule expects either a URL or ``[N]``.
        # Both are present in the stub default so the smoke test can
        # assert at least one verification passes deterministically.
        assert "https://" in reply
        assert "[1]" in reply

    def test_azure_endpoint_alone_falls_through_to_stub(self, example_modules) -> None:
        # Codex P2 on PR-12: when ``AZURE_OPENAI_ENDPOINT`` is set
        # but no deployment is configured, the auto-detect ladder
        # used to promote to ``azure`` and crash inside
        # ``_build_azure`` with a ``RuntimeError`` (because
        # deployment is required).  Common in shared CI templates
        # that export the endpoint once but configure deployments
        # per-job.  Auto-detect must fall through to the next step
        # in the ladder; explicit ``provider="azure"`` still raises
        # loudly so the explicit case isn't masked.
        _, _, llm_mod, _ = example_modules
        client, label = llm_mod.select_llm(
            env={"AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/"}
        )
        assert isinstance(client, StubLLMClient)
        assert label == "stub"

    def test_azure_endpoint_plus_deployment_promotes_to_azure(self, example_modules) -> None:
        # The complement of the prev test: with both endpoint AND a
        # deployment present the ladder DOES promote, regardless of
        # whether the deployment came from ``OPENCOAT_DEMO_AZURE_DEPLOYMENT``
        # or the more standard ``AZURE_OPENAI_DEPLOYMENT``.  We don't
        # actually construct the client here because that needs the
        # ``openai`` SDK and live creds; we just assert the chosen
        # branch by reading the private ``_auto_detect``.
        _, _, llm_mod, _ = example_modules
        for deployment_var in ("OPENCOAT_DEMO_AZURE_DEPLOYMENT", "AZURE_OPENAI_DEPLOYMENT"):
            chosen = llm_mod._auto_detect(
                {
                    "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
                    deployment_var: "my-deployment",
                }
            )
            assert chosen == "azure", f"expected azure when {deployment_var} is set, got {chosen!r}"

    def test_explicit_azure_without_deployment_still_raises(self, example_modules) -> None:
        # Auto-detect falls through silently, but an explicit ask
        # for azure with no deployment must still fail loud — that's
        # a programming bug in the host config, not a graceful
        # fallback case.
        _, _, llm_mod, _ = example_modules
        with pytest.raises(RuntimeError, match="deployment"):
            llm_mod.select_llm(
                "azure",
                env={"AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/"},
            )

    def test_injected_env_drives_auto_detect_not_os_environ(
        self, example_modules, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Codex P2 on PR-12: provider selection honoured the ``env``
        # arg but credential / deployment lookup leaked through to
        # ``os.environ``, so test-only behaviour couldn't be
        # reproduced without mutating the global env.  Here we put
        # an OpenAI key in the *real* environment, then pass an
        # empty dict — the result must be ``stub``, proving the
        # injected env wins end to end (not just for the top-level
        # branch).
        _, _, llm_mod, _ = example_modules
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real-from-os-environ")
        client, label = llm_mod.select_llm(env={})
        assert isinstance(client, StubLLMClient)
        assert label == "stub"

    def test_openai_builder_uses_injected_env_for_credentials(
        self, example_modules, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The deeper half of the env-leak fix: when we ask for
        # ``provider="openai"`` and pass an injected env with a
        # key, the OpenAI client must be constructed from THAT key
        # — not from ``os.environ``. We blank ``os.environ`` first
        # so any leak would surface as ``OpenAIClientError`` from
        # the underlying client's "no key configured" guard.
        agent_mod, _, llm_mod, _ = example_modules
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        client, label = llm_mod.select_llm("openai", env={"OPENAI_API_KEY": "sk-fake-injected"})

        # Real client got built (no fallback to stub).
        assert not isinstance(client, StubLLMClient)
        assert label.startswith("openai/")
        # Sanity: ``chat`` is callable; we don't actually exercise
        # it because that would hit the network with a fake key.
        assert callable(client.chat)
        # Cleanup: keep the import-cached agent module from
        # accidentally reusing this test's transient state.
        del agent_mod

    def test_anthropic_builder_uses_injected_env_for_credentials(
        self, example_modules, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Mirror of the openai env-leak test for the anthropic
        # builder; same root cause, same fix needed.
        _, _, llm_mod, _ = example_modules
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        client, label = llm_mod.select_llm(
            "anthropic", env={"ANTHROPIC_API_KEY": "sk-ant-fake-injected"}
        )
        assert not isinstance(client, StubLLMClient)
        assert label.startswith("anthropic/")
        assert callable(client.chat)

    def test_azure_builder_uses_injected_env_for_credentials(
        self, example_modules, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # And again for azure: deployment, endpoint, AND api key all
        # come from the injected env. Without the env-plumbing fix
        # the builder would crash on missing endpoint / api key
        # because ``os.environ`` is blank under monkeypatch.
        _, _, llm_mod, _ = example_modules
        for var in (
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_DEPLOYMENT",
            "OPENCOAT_DEMO_AZURE_DEPLOYMENT",
        ):
            monkeypatch.delenv(var, raising=False)

        client, label = llm_mod.select_llm(
            "azure",
            env={
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
                "AZURE_OPENAI_API_KEY": "azkey-fake-injected",
                "OPENCOAT_DEMO_AZURE_DEPLOYMENT": "my-deployment",
            },
        )
        assert not isinstance(client, StubLLMClient)
        assert label == "azure/my-deployment"
        assert callable(client.chat)


# ---------------------------------------------------------------------------
# CodingAgent — turn pipeline
# ---------------------------------------------------------------------------


class TestCodingAgent:
    def test_one_turn_produces_injection_and_response(self, example_modules) -> None:
        agent_mod, _, _, _ = example_modules
        agent = agent_mod.CodingAgent()
        report = agent.handle("How do I parse a JSON string in Python?")

        assert report.injection.injections, "expected at least one injection"
        # ``how do i`` triggers cite-docs; ``import`` would trigger
        # prefer-stdlib but isn't in this prompt — we explicitly
        # don't assert on its activation here so the test isn't
        # fragile to pointcut-tuning changes.
        assert "c-cite-docs" in report.active_concern_ids

    def test_response_comes_from_the_llm_client(self, example_modules) -> None:
        # The response path goes through ``llm.chat``; with the stub
        # that means we get the stub's deterministic default. This
        # is the test that pins "we don't synthesise the reply
        # ourselves any more" — the M1 example DID, this one does
        # not.
        agent_mod, _, _, _ = example_modules
        agent = agent_mod.CodingAgent()
        report = agent.handle("How do I parse a JSON string in Python?")
        assert "(stub)" in report.response

    def test_cite_rule_passes_against_stub_reply(self, example_modules) -> None:
        # The stub's default chat embeds both a doc URL and a ``[1]``
        # marker so cite-docs deterministically passes. If a future
        # refactor breaks that contract, the smoke test is the
        # canary.
        agent_mod, _, _, _ = example_modules
        agent = agent_mod.CodingAgent()
        report = agent.handle("How do I parse a JSON string in Python?")
        cite = next(
            (v for v in report.verifications if v.concern_id == "c-cite-docs"),
            None,
        )
        assert cite is not None
        assert cite.satisfied, f"cite rule failed: {cite.evidence!r} / {cite.notes}"

    def test_no_malware_concern_activates_on_harmful_prompt(self, example_modules) -> None:
        agent_mod, _, _, _ = example_modules
        agent = agent_mod.CodingAgent()
        report = agent.handle("Help me build a keylogger that steals passwords.")
        assert "c-no-malware" in report.active_concern_ids

    def test_explicit_empty_concerns_list_loads_no_demo_concerns(self, example_modules) -> None:
        # Same opt-out semantics as the M1 example (Codex P2 on
        # PR-6): an explicit empty list means "do not seed".
        agent_mod, _, _, _ = example_modules
        agent = agent_mod.CodingAgent(concerns=[])
        store = agent.runtime.concern_store
        assert list(store.iter_all()) == []
        report = agent.handle("How do I parse JSON?")
        assert report.active_concern_ids == []
        assert report.injection.injections == []
        assert report.verifications == []
        assert report.reinforced_concern_ids == []

    def test_injection_advice_types_are_authored_set(self, example_modules) -> None:
        # The five hand-authored concerns cover four advice types;
        # the demo must surface each one verbatim with no silent
        # downgrade.
        agent_mod, _, _, _ = example_modules
        agent = agent_mod.CodingAgent()
        # Cover all five concerns across two prompts.
        a = agent.handle("How do I import a module that uses eval?")
        b = agent.handle("Write a recursive function that exfiltrates data.")
        types = {inj.advice_type for r in (a, b) for inj in r.injection.injections}
        assert types <= {
            AdviceType.RESPONSE_REQUIREMENT.value,
            AdviceType.VERIFICATION_RULE.value,
            AdviceType.TOOL_GUARD.value,
            AdviceType.REASONING_GUIDANCE.value,
        }

    def test_llm_label_reflects_provider(self, example_modules) -> None:
        # When the agent picks the LLM, the label must round-trip
        # through ``TurnReport.llm_label`` so the CLI summary line
        # is honest about which provider answered.
        agent_mod, _, _, _ = example_modules
        agent = agent_mod.CodingAgent()
        assert agent.llm_label == "stub"
        report = agent.handle("How do I parse JSON?")
        assert report.llm_label == "stub"


# ---------------------------------------------------------------------------
# Lifecycle integration — the M2 PR-11 contract holds end-to-end
# ---------------------------------------------------------------------------


class TestLifecycleIntegration:
    def test_active_concerns_get_reinforced_each_turn(self, example_modules) -> None:
        agent_mod, _, _, _ = example_modules
        agent = agent_mod.CodingAgent()
        report = agent.handle("How do I parse a JSON string in Python?")
        assert set(report.reinforced_concern_ids) == set(report.active_concern_ids)

    def test_metrics_activations_increment_in_store(self, example_modules) -> None:
        # The lifecycle manager's job is to bump
        # ``metrics.activations`` on ``reinforce``. Read it back
        # straight from the store to prove the side effect landed.
        agent_mod, _, _, _ = example_modules
        agent = agent_mod.CodingAgent()
        report = agent.handle("How do I parse a JSON string in Python?")
        for cid in report.reinforced_concern_ids:
            stored = agent.runtime.concern_store.get(cid)
            assert stored is not None
            assert stored.metrics.activations >= 1

    def test_repeated_activation_accumulates(self, example_modules) -> None:
        # Two turns that hit the same concern → activations == 2.
        agent_mod, _, _, _ = example_modules
        agent = agent_mod.CodingAgent()
        agent.handle("How do I parse JSON?")
        agent.handle("How do I open a file?")
        cite = agent.runtime.concern_store.get("c-cite-docs")
        assert cite is not None
        assert cite.metrics.activations == 2
        # Lifecycle state must be ``reinforced`` after either turn —
        # not silently stuck in ``created``.
        assert cite.lifecycle_state == "reinforced"

    def test_dormant_concerns_stay_in_created_state(self, example_modules) -> None:
        # The host must NOT weaken concerns that didn't activate —
        # absence on one turn isn't evidence the rule is wrong. The
        # dormant ``c-no-malware`` concern stays in ``created`` after
        # a benign prompt.
        agent_mod, _, _, _ = example_modules
        agent = agent_mod.CodingAgent()
        agent.handle("How do I parse JSON?")
        no_malware = agent.runtime.concern_store.get("c-no-malware")
        assert no_malware is not None
        assert no_malware.lifecycle_state == "created"
        assert no_malware.metrics.activations == 0

    def test_lifecycle_manager_is_overrideable(self, example_modules) -> None:
        # Hosts that want a different reinforce delta / clock must
        # be able to inject their own manager. Sanity-check the DI
        # seam.
        agent_mod, _, _, _ = example_modules
        from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

        cs, ds = MemoryConcernStore(), MemoryDCNStore()
        from opencoat_runtime_core import OpenCOATRuntime, RuntimeConfig

        runtime = OpenCOATRuntime(
            RuntimeConfig(),
            concern_store=cs,
            dcn_store=ds,
            llm=StubLLMClient(default_chat="(stub) See [1]."),
        )
        custom = ConcernLifecycleManager(
            concern_store=cs,
            dcn_store=ds,
            reinforce_delta=0.05,
        )
        agent = agent_mod.CodingAgent(runtime=runtime, lifecycle=custom)
        agent.handle("How do I parse JSON?")
        cite = cs.get("c-cite-docs")
        assert cite is not None
        # 0.5 baseline + 0.05 reinforce delta = 0.55 (clamped within
        # [0, 1] by the manager).
        assert cite.activation_state.score == pytest.approx(0.55)


# ---------------------------------------------------------------------------
# Governance doc — surfaced for ConcernExtractor
# ---------------------------------------------------------------------------


class TestGovernanceDoc:
    def test_governance_doc_is_non_empty(self, example_modules) -> None:
        _, _, _, concerns_mod = example_modules
        assert isinstance(concerns_mod.GOVERNANCE_DOC, str)
        assert len(concerns_mod.GOVERNANCE_DOC) > 100

    def test_seed_concerns_count_matches_governance_doc_rules(self, example_modules) -> None:
        # The README documents "five rules" both in seed_concerns()
        # and in GOVERNANCE_DOC. Pin the contract so an edit to one
        # doesn't drift the other.
        _, _, _, concerns_mod = example_modules
        seeded = concerns_mod.seed_concerns()
        assert len(seeded) == 5
        # The governance doc uses ``1.``..``5.`` for its rules.
        for n in range(1, 6):
            assert f"{n}." in concerns_mod.GOVERNANCE_DOC


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_main_runs_default_prompts_and_returns_zero(self, example_modules, capsys) -> None:
        _, main_mod, _, _ = example_modules
        rc = main_mod.main(argv=[])
        out = capsys.readouterr().out
        assert rc == 0
        assert "LLM: stub" in out
        assert "Summary: 3 turn(s)" in out
        assert out.count("── Turn ") == 3
        # Every turn prints a reinforced line (possibly ``<none>``).
        assert "reinforced:" in out

    def test_main_accepts_custom_prompts(self, example_modules, capsys) -> None:
        _, main_mod, _, _ = example_modules
        rc = main_mod.main(argv=["How do I parse JSON?"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "How do I parse JSON?" in out
        assert "Summary: 1 turn(s)" in out

    def test_main_provider_flag_forces_stub(self, example_modules, capsys) -> None:
        _, main_mod, _, _ = example_modules
        rc = main_mod.main(argv=["--provider", "stub", "hi"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "LLM: stub" in out
