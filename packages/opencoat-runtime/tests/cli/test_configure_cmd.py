"""Tests for ``opencoat configure llm``."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import yaml
from opencoat_runtime_cli.commands import configure_cmd


def _ns(**kwargs: object) -> Namespace:
    defaults: dict[str, object] = {
        "yaml": Path("/dev/null"),
        "env": Path("/dev/null"),
        "mode": "env-file",
        "non_interactive": True,
        "provider": "openai",
        "timeout_seconds": 25.0,
        "model": "gpt-4o-mini",
        "bai_api_key": None,
        "bai_model_env": None,
        "bai_base_url": None,
        "openai_api_key": "sk-test-openai",
        "openai_model_env": None,
        "anthropic_api_key": None,
        "anthropic_model_env": None,
        "azure_api_key": None,
        "azure_endpoint": None,
        "azure_deployment": None,
        "openai_base_url": None,
        "anthropic_base_url": None,
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


def test_is_openai_chat_model_id_filters_non_chat() -> None:
    assert configure_cmd._is_openai_chat_model_id("gpt-4o-mini")
    assert configure_cmd._is_openai_chat_model_id("o3-mini")
    assert not configure_cmd._is_openai_chat_model_id("text-embedding-3-small")
    assert not configure_cmd._is_openai_chat_model_id("whisper-1")
    assert not configure_cmd._is_openai_chat_model_id("dall-e-3")


def test_fetch_openai_model_ids_parses_and_filters() -> None:
    payload = {
        "data": [
            {"id": "gpt-4o"},
            {"id": "gpt-4o-mini"},
            {"id": "text-embedding-3-small"},
            {"id": "whisper-1"},
        ]
    }

    class _Resp:
        def read(self) -> bytes:
            return json.dumps(payload).encode()

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    with patch(
        "opencoat_runtime_cli.commands.configure_cmd.urllib.request.urlopen", return_value=_Resp()
    ):
        ids = configure_cmd.fetch_openai_model_ids("sk-test")

    assert ids[0] == "gpt-4o-mini"
    assert "gpt-4o" in ids
    assert "text-embedding-3-small" not in ids


def test_choose_openai_model_paginates() -> None:
    models = [f"gpt-page-{i:02d}" for i in range(25)]
    with patch(
        "opencoat_runtime_cli.commands.configure_cmd.input",
        side_effect=["n", "3"],
    ):
        picked = configure_cmd._choose_openai_model_from_list(models, default=models[0])
    assert picked == "gpt-page-22"


def test_choose_openai_model_rejects_prev_on_first_page() -> None:
    models = [f"gpt-page-{i:02d}" for i in range(25)]
    with patch(
        "opencoat_runtime_cli.commands.configure_cmd.input",
        side_effect=["p", "1"],
    ):
        picked = configure_cmd._choose_openai_model_from_list(models, default=models[0])
    assert picked == "gpt-page-00"


def test_choose_openai_model_rejects_next_on_last_page() -> None:
    models = [f"gpt-page-{i:02d}" for i in range(25)]
    with patch(
        "opencoat_runtime_cli.commands.configure_cmd.input",
        side_effect=["n", "n", "1"],
    ):
        picked = configure_cmd._choose_openai_model_from_list(models, default=models[0])
    assert picked == "gpt-page-20"


def test_choose_openai_model_prev_page() -> None:
    models = [f"gpt-page-{i:02d}" for i in range(25)]
    with patch(
        "opencoat_runtime_cli.commands.configure_cmd.input",
        side_effect=["n", "p", "1"],
    ):
        picked = configure_cmd._choose_openai_model_from_list(models, default=models[0])
    assert picked == "gpt-page-00"


def test_prompt_openai_model_menu_selection() -> None:
    with (
        patch(
            "opencoat_runtime_cli.commands.configure_cmd.fetch_openai_model_ids",
            return_value=["gpt-4o-mini", "gpt-4o"],
        ),
        patch(
            "opencoat_runtime_cli.commands.configure_cmd.input",
            side_effect=["2", ""],
        ),
    ):
        assert configure_cmd._prompt_openai_model("sk-test") == "gpt-4o"


def test_env_key_reads_from_opencoat_env(tmp_path: Path) -> None:
    env_path = tmp_path / "opencoat.env"
    yaml_path = tmp_path / "daemon.yaml"
    env_path.write_text("OPENAI_API_KEY=sk-on-disk\n", encoding="utf-8")
    assert configure_cmd._env_key("OPENAI_API_KEY", env_path, yaml_path) == "sk-on-disk"


def test_collect_interactive_auto_writes_model_to_yaml(tmp_path: Path) -> None:
    env_path = tmp_path / "opencoat.env"
    yaml_path = tmp_path / "daemon.yaml"
    env_path.write_text("OPENAI_API_KEY=sk-existing\n", encoding="utf-8")
    with (
        patch(
            "opencoat_runtime_cli.commands.configure_cmd.getpass.getpass",
            return_value="",
        ),
        patch(
            "opencoat_runtime_cli.commands.configure_cmd.input",
            side_effect=["1", "1", "2", "", "", "", ""],  # mode, provider auto, openai model, azure skips
        ),
        patch(
            "opencoat_runtime_cli.commands.configure_cmd.fetch_openai_model_ids",
            return_value=["gpt-4o-mini", "gpt-4o"],
        ),
    ):
        provider, _mode, env_updates, llm = configure_cmd._collect_interactive(
            env_path=env_path,
            yaml_path=yaml_path,
        )
    assert provider == "auto"
    assert "model" not in llm
    assert env_updates["OPENAI_MODEL"] == "gpt-4o"


def test_collect_interactive_auto_dual_credentials_keeps_per_provider_models(
    tmp_path: Path,
) -> None:
    """Auto with B.AI + OpenAI keys must not let OPENAI_MODEL overwrite BAI via llm.model."""
    env_path = tmp_path / "opencoat.env"
    yaml_path = tmp_path / "daemon.yaml"
    env_path.write_text(
        "BAI_API_KEY=sk-bai\nOPENAI_API_KEY=sk-openai\n",
        encoding="utf-8",
    )
    with (
        patch(
            "opencoat_runtime_cli.commands.configure_cmd.getpass.getpass",
            return_value="",
        ),
        patch(
            "opencoat_runtime_cli.commands.configure_cmd.input",
            side_effect=[
                "1",  # mode env-file
                "1",  # provider auto
                "claude-sonnet-4-6",  # B.AI model (auto path)
                "2",  # OpenAI model menu pick gpt-4o
                "",
                "",
                "",
            ],
        ),
        patch(
            "opencoat_runtime_cli.commands.configure_cmd.fetch_openai_model_ids",
            return_value=["gpt-4o-mini", "gpt-4o"],
        ),
    ):
        provider, _mode, env_updates, llm = configure_cmd._collect_interactive(
            env_path=env_path,
            yaml_path=yaml_path,
        )
    assert provider == "auto"
    assert "model" not in llm
    assert env_updates["BAI_MODEL"] == "claude-sonnet-4-6"
    assert env_updates["OPENAI_MODEL"] == "gpt-4o"


def test_collect_interactive_openai_keeps_existing_key_and_updates_model(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / "opencoat.env"
    yaml_path = tmp_path / "daemon.yaml"
    env_path.write_text("OPENAI_API_KEY=sk-existing\n", encoding="utf-8")
    yaml_path.write_text(
        "llm:\n  provider: openai\n  model: gpt-4o-mini\n  timeout_seconds: 30.0\n",
        encoding="utf-8",
    )
    with (
        patch(
            "opencoat_runtime_cli.commands.configure_cmd.getpass.getpass",
            return_value="",
        ),
        patch(
            "opencoat_runtime_cli.commands.configure_cmd.input",
            side_effect=["1", "3", "2"],  # mode env-file, provider openai, model gpt-4o
        ),
        patch(
            "opencoat_runtime_cli.commands.configure_cmd.fetch_openai_model_ids",
            return_value=["gpt-4o-mini", "gpt-4o"],
        ),
    ):
        provider, mode, env_updates, llm = configure_cmd._collect_interactive(
            env_path=env_path,
            yaml_path=yaml_path,
        )
    assert provider == "openai"
    assert mode == "env-file"
    assert "OPENAI_API_KEY" not in env_updates
    assert llm["model"] == "gpt-4o"


def test_non_interactive_openai_model_only_uses_existing_env_key(tmp_path: Path) -> None:
    y = tmp_path / "daemon.yaml"
    e = tmp_path / "opencoat.env"
    e.write_text("OPENAI_API_KEY=sk-stored\n", encoding="utf-8")
    args = _ns(
        yaml=y,
        env=e,
        mode="env-file",
        provider="openai",
        openai_api_key=None,
        model="gpt-4o",
    )
    assert configure_cmd._configure_llm(args) == 0
    data = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert data["llm"]["model"] == "gpt-4o"
    assert "OPENAI_API_KEY=sk-stored" in e.read_text(encoding="utf-8")


def test_prompt_openai_model_fallback_on_fetch_error() -> None:
    with (
        patch(
            "opencoat_runtime_cli.commands.configure_cmd.fetch_openai_model_ids",
            side_effect=OSError("network down"),
        ),
        patch(
            "opencoat_runtime_cli.commands.configure_cmd.input",
            return_value="gpt-4o",
        ),
    ):
        assert configure_cmd._prompt_openai_model("sk-test") == "gpt-4o"


def test_non_interactive_openai_env_file_writes_yaml_and_env(tmp_path: Path) -> None:
    y = tmp_path / "daemon.yaml"
    e = tmp_path / "opencoat.env"
    args = _ns(yaml=y, env=e, mode="env-file", provider="openai")
    assert configure_cmd._configure_llm(args) == 0
    data = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert data["llm"]["provider"] == "openai"
    assert data["llm"]["model"] == "gpt-4o-mini"
    assert data["llm"]["timeout_seconds"] == 25.0
    text = e.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-test-openai" in text
    assert "sk-test-openai" not in y.read_text()


def test_non_interactive_inline_openai_model_only_keeps_existing_inline_key(
    tmp_path: Path,
) -> None:
    y = tmp_path / "d.yaml"
    e = tmp_path / "e.env"
    y.write_text(
        "llm:\n  provider: openai\n  model: gpt-4o-mini\n"
        "  api_key: sk-inline-saved\n  timeout_seconds: 30.0\n",
        encoding="utf-8",
    )
    args = _ns(
        yaml=y,
        env=e,
        mode="inline",
        provider="openai",
        openai_api_key=None,
        model="gpt-4o",
    )
    assert configure_cmd._configure_llm(args) == 0
    data = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert data["llm"]["api_key"] == "sk-inline-saved"
    assert data["llm"]["model"] == "gpt-4o"


def test_non_interactive_inline_openai_embeds_key_in_yaml(tmp_path: Path) -> None:
    y = tmp_path / "d.yaml"
    e = tmp_path / "e.env"
    args = _ns(
        yaml=y,
        env=e,
        mode="inline",
        openai_api_key="sk-inline",
        openai_base_url="https://example.com/v1",
    )
    assert configure_cmd._configure_llm(args) == 0
    data = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert data["llm"]["api_key"] == "sk-inline"
    assert data["llm"]["base_url"] == "https://example.com/v1"
    assert not e.exists()


def test_yaml_merge_preserves_other_top_level_keys(tmp_path: Path) -> None:
    y = tmp_path / "daemon.yaml"
    y.write_text(
        "ipc:\n  http:\n    enabled: true\n    host: 127.0.0.1\n    port: 7878\n",
        encoding="utf-8",
    )
    args = _ns(
        yaml=y,
        env=tmp_path / "e.env",
        mode="inline",
        provider="stub",
        model=None,
        openai_api_key=None,
        timeout_seconds=30.0,
    )
    assert configure_cmd._configure_llm(args) == 0
    data = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert data["ipc"]["http"]["port"] == 7878
    assert data["llm"]["provider"] == "stub"


def test_rerun_env_file_after_inline_drops_inline_secrets(tmp_path: Path) -> None:
    """Switching ``--mode inline`` → ``--mode env-file`` must scrub stale secrets.

    Regression for Codex P1 on PR-51: the previous merge was an
    unconditional ``{**old, **new}`` so an ``api_key`` written in
    inline mode survived a follow-up env-file run, defeating the
    "YAML has no secrets" promise the wizard prints.
    """
    y = tmp_path / "daemon.yaml"
    e = tmp_path / "opencoat.env"

    # 1. seed inline mode → api_key + base_url land in yaml
    inline_args = _ns(
        yaml=y,
        env=e,
        mode="inline",
        openai_api_key="sk-inline-old",
        openai_base_url="https://gw.example.com/v1",
    )
    assert configure_cmd._configure_llm(inline_args) == 0
    inline_data = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert inline_data["llm"]["api_key"] == "sk-inline-old"

    # 2. re-run in env-file mode with a different key
    env_args = _ns(
        yaml=y,
        env=e,
        mode="env-file",
        provider="openai",
        openai_api_key="sk-fresh-env",
    )
    assert configure_cmd._configure_llm(env_args) == 0

    data = yaml.safe_load(y.read_text(encoding="utf-8"))
    # Inline secrets are gone from disk…
    assert "api_key" not in data["llm"]
    assert "endpoint" not in data["llm"]
    assert "deployment" not in data["llm"]
    # …and the raw YAML text doesn't contain the stale credential either.
    assert "sk-inline-old" not in y.read_text(encoding="utf-8")
    # The new key lives in the env file (env-file mode).
    assert "OPENAI_API_KEY=sk-fresh-env" in e.read_text(encoding="utf-8")
    # Non-secret llm fields (provider/model/timeout) still merge normally.
    assert data["llm"]["provider"] == "openai"
    assert data["llm"]["model"] == "gpt-4o-mini"


def test_rerun_inline_azure_after_inline_openai_replaces_endpoint(tmp_path: Path) -> None:
    """Inline-to-inline across providers replaces endpoint/deployment, not append."""
    y = tmp_path / "daemon.yaml"
    e = tmp_path / "opencoat.env"

    first = _ns(
        yaml=y,
        env=e,
        mode="inline",
        openai_api_key="sk-openai-1",
    )
    assert configure_cmd._configure_llm(first) == 0

    second = _ns(
        yaml=y,
        env=e,
        mode="inline",
        provider="azure",
        model=None,
        openai_api_key=None,
        bai_api_key=None,
        azure_api_key="az-key",
        azure_endpoint="https://az.example.com",
        azure_deployment="dep-1",
    )
    assert configure_cmd._configure_llm(second) == 0
    data = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert data["llm"]["api_key"] == "az-key"
    assert data["llm"]["endpoint"] == "https://az.example.com"
    assert data["llm"]["deployment"] == "dep-1"
    # Stale provider key from the first run is gone.
    assert "sk-openai-1" not in y.read_text(encoding="utf-8")


def test_non_interactive_inline_auto_rejected(tmp_path: Path) -> None:
    import pytest

    args = _ns(
        yaml=tmp_path / "d.yaml",
        env=tmp_path / "e.env",
        mode="inline",
        provider="auto",
        model=None,
        openai_api_key="sk-x",
        bai_api_key=None,
    )
    with pytest.raises(SystemExit) as excinfo:
        configure_cmd._configure_llm(args)
    assert excinfo.value.code == 2
    p = tmp_path / "x.env"
    p.write_text("A=1\n# c\nB=two\n", encoding="utf-8")
    assert configure_cmd._parse_env_file(p) == {"A": "1", "B": "two"}


# ---------------------------------------------------------------------------
# configure daemon
# ---------------------------------------------------------------------------


def _daemon_ns(**kwargs: object) -> Namespace:
    defaults: dict[str, object] = {
        "yaml": Path("/dev/null"),
        "concern_db": Path("/dev/null/concerns.sqlite"),
        "dcn_db": Path("/dev/null/dcn.sqlite"),
        "http_host": "127.0.0.1",
        "http_port": 7878,
        "http_path": "/rpc",
        "pid_file": Path("/dev/null/opencoat.pid"),
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


def test_configure_daemon_writes_sqlite_storage(tmp_path: Path) -> None:
    y = tmp_path / "daemon.yaml"
    cdb = tmp_path / "store" / "concerns.sqlite"
    ddb = tmp_path / "store" / "dcn.sqlite"
    args = _daemon_ns(yaml=y, concern_db=cdb, dcn_db=ddb, pid_file=tmp_path / "opencoat.pid")
    assert configure_cmd._configure_daemon(args) == 0

    data = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert data["storage"]["concern_store"] == {"kind": "sqlite", "path": str(cdb)}
    assert data["storage"]["dcn_store"] == {"kind": "sqlite", "path": str(ddb)}
    assert data["ipc"]["http"] == {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 7878,
        "path": "/rpc",
    }
    # Parent dir for the sqlite files exists after configure runs.
    assert cdb.parent.is_dir()


def test_configure_daemon_preserves_existing_llm_block(tmp_path: Path) -> None:
    y = tmp_path / "daemon.yaml"
    y.write_text(
        "llm:\n  provider: openai\n  model: gpt-4o-mini\n  timeout_seconds: 30.0\n",
        encoding="utf-8",
    )
    args = _daemon_ns(
        yaml=y,
        concern_db=tmp_path / "c.sqlite",
        dcn_db=tmp_path / "d.sqlite",
        pid_file=tmp_path / "opencoat.pid",
    )
    assert configure_cmd._configure_daemon(args) == 0

    data = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert data["llm"]["provider"] == "openai"
    assert data["llm"]["model"] == "gpt-4o-mini"
    assert data["storage"]["concern_store"]["kind"] == "sqlite"


def test_configure_daemon_then_llm_round_trip(tmp_path: Path) -> None:
    """Either-order: configure daemon → configure llm leaves both blocks intact."""
    y = tmp_path / "daemon.yaml"
    daemon_args = _daemon_ns(
        yaml=y,
        concern_db=tmp_path / "c.sqlite",
        dcn_db=tmp_path / "d.sqlite",
        pid_file=tmp_path / "opencoat.pid",
    )
    assert configure_cmd._configure_daemon(daemon_args) == 0

    llm_args = _ns(yaml=y, env=tmp_path / "e.env", mode="env-file", provider="openai")
    assert configure_cmd._configure_llm(llm_args) == 0

    data = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert data["storage"]["concern_store"]["kind"] == "sqlite"
    assert data["llm"]["provider"] == "openai"
    assert data["ipc"]["http"]["port"] == 7878
