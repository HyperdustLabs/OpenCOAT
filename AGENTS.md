# Agent instructions (OpenCOAT monorepo)

All contributors — **including AI coding agents** — follow [CONTRIBUTING.md](CONTRIBUTING.md).

## Git: pull requests only

- **Do not** push directly to `main`.
- Use a short-lived branch (`feat/`, `fix/`, `docs/`, `chore/`, …), run `./scripts/verify.sh`, then open a PR and squash-merge after CI is green.
- Cursor loads the same rule from [`.cursor/rules/contributing-pr-only.mdc`](.cursor/rules/contributing-pr-only.mdc).

When the user asks to **commit** or **push**, default to **branch + PR** (report the PR URL), not `git push origin main`.

Install / dogfood skill (daemon, bridge): [OpenCOAT skill](https://www.opencoat.ai/SKILL.md) — includes **Monorepo git workflow** for changes in this repository.
