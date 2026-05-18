# ADR 0010 — Concern unit, AOP executable syntax (AspectJ)

## Status

Accepted (v0.2).

## Context

OpenCOAT keeps **Concern** as the only first-class cognitive and runtime unit
(ADR-0001). The activation mechanism remains AOP (ADR-0002), but authors and
the Concern Graph should speak **AOP (AspectJ) vocabulary** rather than inventing
parallel graph primitives such as “Concern suppresses Concern” as the primary
weave semantics.

## Decision

1. **Unit name** stays `Concern` / `MetaConcern`. We do **not** introduce a
   separate `Aspect` runtime entity.
2. **Executable shape** on each Concern uses AOP lists:
   - `pointcuts[]` — optional `expression` (surface syntax) + structured `match`
   - `advices[]` — `kind`: `before|after|around|…`, `pointcut_ref`, `effect`
   - `declarations[]` — `declare_precedence`, `inter_type`
3. **Legacy fields** `pointcut`, `advice`, `weaving_policy` remain valid; the
   protocol normalizes legacy ↔ AOP on load via
   `opencoat_runtime_protocol.aop.sync_concern_aop`.
4. **Domain templates** (`tool_guard`, `reasoning_guidance`, …) move to
   `advice.template` (or legacy `advice.type`); they are **not** AOP joinpoint
   kinds.
5. **Concern Graph edges** prefer `ConcernGraphEdgeType` /
   `declares_precedence_over` over `suppresses` for runtime ordering. Semantic
   lineage edges (`derived_from`, `generalizes`, …) use `relation.layer:
   semantic` and stay out of the weave resolver path.
6. **Meta concerns** target `adviceexecution` joinpoints (catalog) for
   concern-of-concern weaving.

## Consequences

- Matcher / weaver read `primary_pointcut()` / `primary_advice()` /
  `primary_weaving()` so both authoring styles work.
- New examples and bridge docs should show AOP-shaped JSON where possible.
- Full `declare precedence` in `ConflictResolver` and multi-advice ordering are
  follow-up PRs; this ADR locks the schema and normalization contract.

## References

- ADR-0001 (Concern as unit), ADR-0002 (AOP mechanism), ADR-0008 (meta concern)
- v0.2 §5.1 Concern schema, §4.7 JP automation
