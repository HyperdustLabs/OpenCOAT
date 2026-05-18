"""Tests for ``opencoat_runtime_daemon.build_runtime`` (M4 PR-17)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from opencoat_runtime_core import OpenCOATRuntime
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_daemon import build_runtime
from opencoat_runtime_daemon.config.loader import (
    DaemonConfig,
    IPCEndpoint,
    IPCSettings,
    LLMSettings,
    ObservabilitySettings,
    PluginSettings,
    StorageBackend,
    StorageSettings,
    load_config,
)
from opencoat_runtime_daemon.runtime_builder import warm_persistent_stores
from opencoat_runtime_protocol import (
    Advice,
    AdviceType,
    Concern,
    JoinpointEvent,
    Pointcut,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
)
from opencoat_runtime_protocol.envelopes import PointcutMatch
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore
from opencoat_runtime_storage.sqlite import SqliteConcernStore, SqliteDCNStore


def _bare_config(
    *,
    concern: StorageBackend,
    dcn: StorageBackend,
    llm: LLMSettings,
) -> DaemonConfig:
    return DaemonConfig(
        storage=StorageSettings(concern_store=concern, dcn_store=dcn),
        llm=llm,
        ipc=IPCSettings(inproc=IPCEndpoint(enabled=True)),
        observability=ObservabilitySettings(),
        plugins=PluginSettings(),
    )


def _concern() -> Concern:
    return Concern(
        id="c-builder",
        name="Builder smoke",
        description="hermetic concern for the builder tests",
        pointcut=Pointcut(match=PointcutMatch(any_keywords=["refund"])),
        advice=Advice(type=AdviceType.REASONING_GUIDANCE, content="be kind"),
        weaving_policy=WeavingPolicy(
            mode=WeavingOperation.INSERT,
            level=WeavingLevel.PROMPT_LEVEL,
            target="reasoning.hints",
            priority=0.5,
        ),
    )


def _joinpoint() -> JoinpointEvent:
    return JoinpointEvent(
        id="jp-build",
        level=2,
        name="before_response",
        host="builder-test",
        agent_session_id="sess",
        ts=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
        payload={"text": "refund please", "raw_text": "refund please"},
    )


class TestDefaults:
    def test_default_config_with_no_credentials_yields_stub_fallback(self) -> None:
        # Default config ships ``provider: auto``. An empty env mapping
        # has none of the marker variables, so auto-detection must
        # fall back to stub — with the *distinct* ``stub-fallback``
        # label and a fix-it hint so the operator sees it loudly in
        # the daemon log + CLI banner.
        with build_runtime(load_config(), env={}) as built:
            assert isinstance(built.runtime, OpenCOATRuntime)
            assert isinstance(built.runtime.concern_store, MemoryConcernStore)
            assert isinstance(built.runtime.dcn_store, MemoryDCNStore)
            assert built.llm_label == "stub-fallback"
            assert built.llm_info.kind == "stub"
            assert built.llm_info.real is False
            assert built.llm_info.requested == "auto"
            assert "OPENAI_API_KEY" in built.llm_info.hint  # actionable hint
            assert isinstance(built.runtime._llm, StubLLMClient)  # type: ignore[attr-defined]

    def test_default_config_with_bai_key_picks_bai(self) -> None:
        with build_runtime(load_config(), env={"BAI_API_KEY": "sk-bai-auto"}) as built:
            assert built.llm_info.kind == "bai"
            assert built.llm_info.real is True
            assert built.llm_info.requested == "auto"
            assert built.llm_label.startswith("bai/")
            assert built.llm_info.hint == ""

    def test_default_config_with_openai_key_picks_openai(self) -> None:
        # Same default config, but the operator exported a real key.
        # Auto-detection must pick OpenAI and ``llm_info.real`` flips
        # to ``True`` — this is the headline value prop of ``auto``.
        with build_runtime(load_config(), env={"OPENAI_API_KEY": "sk-fake-auto"}) as built:
            assert built.llm_info.kind == "openai"
            assert built.llm_info.real is True
            assert built.llm_info.requested == "auto"
            assert built.llm_label.startswith("openai/")
            assert built.llm_info.hint == ""

    def test_bai_precedence_over_openai_in_auto(self) -> None:
        with build_runtime(
            load_config(),
            env={"BAI_API_KEY": "sk-bai", "OPENAI_API_KEY": "sk-openai"},
        ) as built:
            assert built.llm_info.kind == "bai"

    def test_explicit_provider_stub_skips_fallback_hint(self) -> None:
        # ``provider: stub`` is a deliberate choice (hermetic tests,
        # examples) and must not be nagged about. Distinguished from
        # ``stub-fallback`` by both ``label`` and ``hint``.
        cfg = _bare_config(
            concern=StorageBackend(kind="memory"),
            dcn=StorageBackend(kind="memory"),
            llm=LLMSettings(provider="stub"),
        )
        with build_runtime(cfg, env={}) as built:
            assert built.llm_label == "stub"
            assert built.llm_info.kind == "stub"
            assert built.llm_info.requested == "stub"
            assert built.llm_info.hint == ""

    def test_close_is_idempotent_on_memory(self) -> None:
        built = build_runtime(load_config(), env={})
        built.close()
        built.close()

    def test_warm_persistent_stores_logs_counts(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO)
        with build_runtime(load_config(), env={}) as built:
            warm_persistent_stores(built.runtime)
        assert any("warm-up complete" in r.message for r in caplog.records)


class TestStorageSqlite:
    def test_sqlite_concern_and_dcn_round_trip(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        cfg = _bare_config(
            concern=StorageBackend(kind="sqlite", path=str(db)),
            dcn=StorageBackend(kind="sqlite", path=str(db)),
            llm=LLMSettings(provider="stub"),
        )

        c = _concern()
        with build_runtime(cfg, env={}) as built:
            assert isinstance(built.runtime.concern_store, SqliteConcernStore)
            assert isinstance(built.runtime.dcn_store, SqliteDCNStore)
            built.runtime.concern_store.upsert(c)

        with build_runtime(cfg, env={}) as built2:
            assert built2.runtime.concern_store.get("c-builder") is not None
            inj = built2.runtime.on_joinpoint(_joinpoint())
            assert inj is not None
            assert any(i.concern_id == "c-builder" for i in inj.injections)

    def test_close_releases_sqlite_handles(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        cfg = _bare_config(
            concern=StorageBackend(kind="sqlite", path=str(db)),
            dcn=StorageBackend(kind="sqlite", path=str(db)),
            llm=LLMSettings(provider="stub"),
        )
        built = build_runtime(cfg, env={})
        built.close()
        with pytest.raises(Exception):
            built.runtime.concern_store.get("c-builder")

    def test_unknown_storage_kind_raises(self) -> None:
        cfg = _bare_config(
            concern=StorageBackend(kind="postgres"),
            dcn=StorageBackend(kind="memory"),
            llm=LLMSettings(provider="stub"),
        )
        with pytest.raises(ValueError, match="concern_store backend"):
            build_runtime(cfg, env={})


class TestLLM:
    def test_unknown_provider_raises(self) -> None:
        cfg = _bare_config(
            concern=StorageBackend(kind="memory"),
            dcn=StorageBackend(kind="memory"),
            llm=LLMSettings(provider="not-a-thing"),
        )
        with pytest.raises(ValueError, match=r"llm\.provider"):
            build_runtime(cfg, env={})

    def test_openai_uses_injected_env_credentials(self) -> None:
        cfg = _bare_config(
            concern=StorageBackend(kind="memory"),
            dcn=StorageBackend(kind="memory"),
            llm=LLMSettings(provider="openai"),
        )
        with build_runtime(cfg, env={"OPENAI_API_KEY": "sk-fake-builder"}) as built:
            assert built.llm_label.startswith("openai/")
            assert not isinstance(built.runtime._llm, StubLLMClient)  # type: ignore[attr-defined]

    def test_anthropic_uses_injected_env_credentials(self) -> None:
        cfg = _bare_config(
            concern=StorageBackend(kind="memory"),
            dcn=StorageBackend(kind="memory"),
            llm=LLMSettings(provider="anthropic"),
        )
        with build_runtime(cfg, env={"ANTHROPIC_API_KEY": "sk-ant-fake"}) as built:
            assert built.llm_label.startswith("anthropic/")
            assert not isinstance(built.runtime._llm, StubLLMClient)  # type: ignore[attr-defined]

    def test_azure_requires_deployment(self) -> None:
        cfg = _bare_config(
            concern=StorageBackend(kind="memory"),
            dcn=StorageBackend(kind="memory"),
            llm=LLMSettings(provider="azure"),
        )
        with pytest.raises(RuntimeError, match="deployment"):
            build_runtime(
                cfg,
                env={"AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/"},
            )

    def test_azure_with_deployment_and_env(self) -> None:
        cfg = _bare_config(
            concern=StorageBackend(kind="memory"),
            dcn=StorageBackend(kind="memory"),
            llm=LLMSettings(provider="azure"),
        )
        with build_runtime(
            cfg,
            env={
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
                "AZURE_OPENAI_API_KEY": "azkey-fake",
                "AZURE_OPENAI_DEPLOYMENT": "my-deployment",
            },
        ) as built:
            assert built.llm_label == "azure/my-deployment"

    def test_openai_honours_config_overrides(self) -> None:
        cfg = _bare_config(
            concern=StorageBackend(kind="memory"),
            dcn=StorageBackend(kind="memory"),
            llm=LLMSettings.model_validate(
                {
                    "provider": "openai",
                    "timeout_seconds": 5.0,
                    "model": "gpt-9000-imaginary",
                    "api_key": "sk-from-config",
                }
            ),
        )
        with build_runtime(cfg, env={}) as built:
            assert built.llm_label == "openai/gpt-9000-imaginary"


class TestAutoProvider:
    """``provider: auto`` — the new default.

    Pinned contracts the daemon (and the docs that point at it) rely
    on:

    1. ``OPENAI_API_KEY`` beats ``ANTHROPIC_API_KEY`` beats
       ``AZURE_OPENAI_*`` (matches install precedence in the docs).
    2. Azure auto-detection requires *both* the API key and the
       deployment — picking ``provider=azure`` without a deployment
       would just rediscover the same RuntimeError ``_build_azure``
       raises later. Without the deployment, auto must keep looking
       (or fall back to stub).
    3. No credentials → ``stub-fallback``, not ``stub`` — distinct
       label + fix-it hint so the operator can tell "I deliberately
       picked stub" from "the daemon couldn't find my key".
    4. The chosen provider's ``LLMInfo`` carries
       ``requested="auto"`` so dashboards can show "we asked for
       auto, we got openai".
    """

    def _cfg(self) -> DaemonConfig:
        return _bare_config(
            concern=StorageBackend(kind="memory"),
            dcn=StorageBackend(kind="memory"),
            llm=LLMSettings(provider="auto"),
        )

    def test_picks_openai_when_openai_key_present(self) -> None:
        with build_runtime(self._cfg(), env={"OPENAI_API_KEY": "sk-fake"}) as built:
            assert built.llm_info.kind == "openai"
            assert built.llm_info.real is True
            assert built.llm_info.requested == "auto"
            assert built.llm_label.startswith("openai/")

    def test_picks_anthropic_when_only_anthropic_key_present(self) -> None:
        with build_runtime(self._cfg(), env={"ANTHROPIC_API_KEY": "sk-ant-fake"}) as built:
            assert built.llm_info.kind == "anthropic"
            assert built.llm_info.real is True
            assert built.llm_label.startswith("anthropic/")

    def test_picks_azure_when_only_azure_creds_present(self) -> None:
        with build_runtime(
            self._cfg(),
            env={
                "AZURE_OPENAI_API_KEY": "azkey",
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
                "AZURE_OPENAI_DEPLOYMENT": "my-deployment",
            },
        ) as built:
            assert built.llm_info.kind == "azure"
            assert built.llm_info.real is True
            assert built.llm_label == "azure/my-deployment"

    def test_skips_azure_when_deployment_missing(self) -> None:
        # API key alone isn't enough — auto must keep looking (find
        # nothing) and fall back to stub rather than handing
        # ``_build_azure`` a deployment-less config that it'd reject.
        with build_runtime(
            self._cfg(),
            env={"AZURE_OPENAI_API_KEY": "azkey"},
        ) as built:
            assert built.llm_info.kind == "stub"
            assert built.llm_info.label == "stub-fallback"

    def test_openai_beats_anthropic(self) -> None:
        with build_runtime(
            self._cfg(),
            env={"OPENAI_API_KEY": "sk-fake", "ANTHROPIC_API_KEY": "sk-ant"},
        ) as built:
            assert built.llm_info.kind == "openai"

    def test_anthropic_beats_azure(self) -> None:
        with build_runtime(
            self._cfg(),
            env={
                "ANTHROPIC_API_KEY": "sk-ant",
                "AZURE_OPENAI_API_KEY": "az",
                "AZURE_OPENAI_DEPLOYMENT": "d",
            },
        ) as built:
            assert built.llm_info.kind == "anthropic"

    def test_no_credentials_falls_back_to_stub_with_hint(self) -> None:
        with build_runtime(self._cfg(), env={}) as built:
            assert built.llm_info.kind == "stub"
            assert built.llm_info.label == "stub-fallback"
            assert built.llm_info.real is False
            assert built.llm_info.requested == "auto"
            # The hint must enumerate the env vars to set so users can
            # just read the daemon log and fix the problem.
            hint = built.llm_info.hint
            assert "OPENAI_API_KEY" in hint
            assert "ANTHROPIC_API_KEY" in hint
            assert "AZURE_OPENAI" in hint

    def test_stub_fallback_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        # The daemon log is the operator's first signal — drop a
        # WARNING (not INFO) so it surfaces in ``opencoat runtime
        # status`` style log scans and any monitoring stack that
        # filters by level.
        import logging

        caplog.set_level(logging.WARNING, logger="opencoat_runtime_daemon.runtime_builder")
        with build_runtime(self._cfg(), env={}):
            pass
        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "stub-fallback" in r.getMessage()
        ]
        assert warnings, "expected stub-fallback WARNING in daemon log"

    def test_real_provider_does_not_log_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        caplog.set_level(logging.WARNING, logger="opencoat_runtime_daemon.runtime_builder")
        with build_runtime(self._cfg(), env={"OPENAI_API_KEY": "sk-fake"}):
            pass
        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "stub-fallback" in r.getMessage()
        ]
        assert not warnings, f"unexpected WARNING(s): {[r.getMessage() for r in warnings]}"


class TestExplicitEnvIsHermetic:
    """Codex P1 on PR-17: explicit ``env=`` must not leak to ``os.environ``."""

    def test_openai_without_key_in_explicit_env_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real-from-os-environ")
        cfg = _bare_config(
            concern=StorageBackend(kind="memory"),
            dcn=StorageBackend(kind="memory"),
            llm=LLMSettings(provider="openai"),
        )
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            build_runtime(cfg, env={})

    def test_anthropic_without_key_in_explicit_env_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
        cfg = _bare_config(
            concern=StorageBackend(kind="memory"),
            dcn=StorageBackend(kind="memory"),
            llm=LLMSettings(provider="anthropic"),
        )
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            build_runtime(cfg, env={})

    def test_azure_without_credentials_in_explicit_env_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Both endpoint and api_key live in os.environ; the explicit
        # env mapping only carries the deployment — every other
        # credential must come from the injected env, not os.environ.
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://leak.openai.azure.com/")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "leaked-key")
        cfg = _bare_config(
            concern=StorageBackend(kind="memory"),
            dcn=StorageBackend(kind="memory"),
            llm=LLMSettings(provider="azure"),
        )
        with pytest.raises(RuntimeError, match=r"AZURE_OPENAI_(ENDPOINT|API_KEY)"):
            build_runtime(cfg, env={"AZURE_OPENAI_DEPLOYMENT": "my-deployment"})


class TestAzureExtras:
    """Codex P2 on PR-17: Azure must honour timeout + OPENAI_API_VERSION env."""

    @staticmethod
    def _patch_azure(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
        """Replace the lazy Azure client with a kwargs-capturing stub."""
        import opencoat_runtime_llm as llm_pkg

        captured: dict[str, object] = {}

        def fake_client(**kwargs: object) -> object:
            captured.update(kwargs)
            return object()

        monkeypatch.setattr(llm_pkg, "AzureOpenAILLMClient", fake_client, raising=False)
        return captured

    def test_azure_picks_api_version_from_openai_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = self._patch_azure(monkeypatch)
        cfg = _bare_config(
            concern=StorageBackend(kind="memory"),
            dcn=StorageBackend(kind="memory"),
            llm=LLMSettings(provider="azure"),
        )
        build_runtime(
            cfg,
            env={
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
                "AZURE_OPENAI_API_KEY": "azkey-fake",
                "AZURE_OPENAI_DEPLOYMENT": "my-deployment",
                "OPENAI_API_VERSION": "2099-12-31",
            },
        )
        assert captured["api_version"] == "2099-12-31"

    def test_azure_propagates_timeout_seconds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = self._patch_azure(monkeypatch)
        cfg = _bare_config(
            concern=StorageBackend(kind="memory"),
            dcn=StorageBackend(kind="memory"),
            llm=LLMSettings(provider="azure", timeout_seconds=42.5),
        )
        build_runtime(
            cfg,
            env={
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
                "AZURE_OPENAI_API_KEY": "azkey-fake",
                "AZURE_OPENAI_DEPLOYMENT": "my-deployment",
            },
        )
        assert captured["timeout_seconds"] == 42.5
