# AtlasRAG

An internal knowledge assistant for companies: it answers employee questions from company
documents (policies, technical guides, PDF reports with tables) with **document-level
permissions**, **citations**, an **explicit five-status answer contract** (including
source-conflict detection), **Arabic and English measured per language**, automated
evaluation, and a real deployment.

See [IDEA.md](IDEA.md) for the full design, the nine-phase build plan, and the rationale
behind every stack decision.

## The answer contract

Every answer carries exactly one status:

| Status | Meaning |
|---|---|
| `answered` | Grounded answer with inline citations |
| `insufficient_evidence` | Correct refusal, plus exactly what information is missing |
| `conflicting_evidence` | Sources disagree — both sides returned with their sources |
| `access_restricted` | Evidence exists but the user's roles don't permit it (audit-side) |
| `out_of_scope` | Not a question this corpus answers |

## Layout

```
apps/         process entrypoints (api, worker) — wiring only, no domain logic
src/atlasrag/
  bootstrap/  config, DI container, lifecycle, logging
  contracts/  the shared vocabulary: answer, citation, conflict, retrieval, events
  modules/    business capabilities — independent of one another
  platform/   technical capabilities behind interfaces (db, cache, llm, embeddings, ...)
migrations/   alembic
evals/        golden + synthetic datasets, metrics, experiments, runners, reports
corpus/       source documents, manifests, generated material
tests/        unit, integration, e2e, architecture (module boundaries), fixtures
frontend/     Next.js chat UI: streaming, citations, status badges, feedback
infra/        compose, docker, caddy, langfuse, monitoring
docs/         architecture, ADRs, diagrams, runbooks
```

The dependency rule: `modules → platform → contracts`. Modules never import each other;
`tests/architecture` enforces it via import-linter.

## Getting started

```bash
uv sync --all-extras --dev
cp .env.example .env          # fill in the keys
make dev                      # postgres+pgvector, redis, langfuse
make migrate
make ingest
make eval                     # writes a report to evals/reports/
```

## Scoreboard

Baseline and per-phase results land in `evals/reports/`, each tagged with its commit hash
and broken down **overall / EN / AR**. The table below is filled in from Phase 1 onward.

| Metric | Baseline | Current | Target |
|---|---|---|---|
| hit_rate@5 | — | — | ≥ 0.85 |
| RAGAS faithfulness | — | — | ≥ 0.90 |
| Correct refusal | — | — | ≥ 0.95 |
| Conflict detection | — | — | ≥ 0.80 |
| Status accuracy | — | — | ≥ 0.90 |
