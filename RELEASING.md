# Releasing OpenCOAT

How to cut a new version of the 3 OpenCOAT packages.

| Package                       | Role                                       |
| ----------------------------- | ------------------------------------------ |
| `opencoat-runtime-protocol`   | JSON Schemas + pydantic envelopes (contract) |
| `opencoat-runtime`            | runtime stack: core + storage + llm + daemon + CLI |
| `opencoat-runtime-host`       | host SDK + first-party framework adapters  |

All three are versioned in lockstep: a release bumps every `pyproject.toml`
to the same `X.Y.Z` and tags `vX.Y.Z`.

---

## 0. One-time PyPI setup (~5 min)

1. **Create a PyPI account** at <https://pypi.org/account/register/> with a
   HyperdustLabs-owned email. Enable 2FA (required since 2024-01-01).

2. **Generate an API token** at
   <https://pypi.org/manage/account/token/>:
   * Token name: `OpenCOAT release CI`
   * Scope: **Entire account** (the 3 projects don't exist yet — narrow this
     down to project-scoped after the first publish lands).

3. **Add the token to GitHub Actions** at
   <https://github.com/HyperdustLabs/OpenCOAT/settings/secrets/actions>:
   * Name: `PYPI_API_TOKEN`
   * Value: the `pypi-…` string from step 2.

That's it. No Trusted Publishing, no TestPyPI smoke test, no GitHub
Environments. Those are reasonable upgrades for v0.3+ once the
release cadence stabilises — see §Future.

---

## 1. Cutting a release (~5 min)

```bash
# 0. clean checkout of main, fully synced
git checkout main && git pull
bash scripts/verify.sh

# 1. bump every pyproject in lockstep (3 files)
#    pick X.Y.Z per SemVer:
#      0.1.3 → 0.1.4    patch (B.AI LLM, JoinpointDiscovery, AspectJ concerns, OpenClaw bridge verify)
#      0.1.2 → 0.1.3    patch (ConcernBuilder MVP, gpt-5 tokens, OpenClaw bridge)
#      0.1.1 → 0.1.2    patch (ship CLI `service` + PyPI/doc alignment)
#      0.1.0 → 0.2.0    minor (additive API)
#      0.1.0 → 1.0.0    major (breaking)
$EDITOR packages/opencoat-runtime-protocol/pyproject.toml \
        packages/opencoat-runtime/pyproject.toml \
        packages/opencoat-runtime-host/pyproject.toml

# 2. regenerate the lockfile
uv lock

# 3. commit + tag + push
git commit -am "chore(release): v0.1.4"
git tag v0.1.4
git push origin main --tags
```

CI (`.github/workflows/release.yml`) then:

1. Builds 3 wheels + 3 sdists with `uv build`.
2. Runs `twine check` (PEP 639 metadata sanity).
3. `uv publish` uploads all 6 artefacts to PyPI in one call.

Tag → PyPI is ~3 minutes.

---

## 2. Post-release verification

```bash
# fresh venv install — exercises the runtime + protocol install path
pipx install --force "opencoat-runtime==X.Y.Z"
opencoat --version

# host integrators
pip install "opencoat-runtime-host==X.Y.Z[openclaw]"
python -c "from opencoat_runtime_host_sdk import Client; print(Client)"
```

Then cut a GitHub release with the auto-generated changelog at
<https://github.com/HyperdustLabs/OpenCOAT/releases/new?tag=vX.Y.Z>.

---

## 3. Common gotchas

| symptom | fix |
| --- | --- |
| `uv publish` fails with `400 Bad Request: File already exists` | someone already pushed this version. PyPI never lets you overwrite. Bump to the next patch. |
| `twine check` complains about `License-Expression` | bump to `hatchling>=1.27` (PEP 639 native support) |
| Wheel is empty | `[tool.hatch.build.targets.wheel] packages = [...]` is wrong; `uv build` locally + `unzip -l dist/*.whl` to confirm |
| Version mismatch (one package on 0.2.0, others on 0.1.0) | always bump all 3 `pyproject.toml` files in the same commit |
| `pipx install opencoat-runtime` pulls old version | run `pipx upgrade opencoat-runtime` or `pipx install --force` |

---

## 4. Dry-run a release without tagging

```text
GitHub → Actions → Release → Run workflow → dry_run: true
```

Builds + `twine check` in CI, uploads artefacts to the run, **does not**
push to PyPI. Useful for verifying a release candidate end-to-end.

---

## 5. Future: when to upgrade the pipeline

These are non-blocking; the simple token flow above is fine through v0.2.

* **Trusted Publishing (OIDC)** — eliminates the long-lived token.
  Add a "Pending Publisher" for each of the 3 projects on PyPI pointing
  at `release.yml`, set `permissions: id-token: write` on the job, drop
  the `UV_PUBLISH_TOKEN` env. ~5 min of forms.

* **GitHub Environments + required reviewers** — add a `pypi` environment
  to require a manual approval click on every prod publish. Useful when
  the team grows beyond a single maintainer.

* **TestPyPI smoke step** — add a parallel job that publishes to
  `test.pypi.org` on `workflow_dispatch`. Useful if a publish ever
  breaks; today the dry-run path covers 95% of that need.

* **PyPI Organisation transfer** — once HyperdustLabs is registered as a
  PyPI org, transfer the 3 projects from the individual account to the
  org. No code change; Trusted Publishing keeps working per-project.
