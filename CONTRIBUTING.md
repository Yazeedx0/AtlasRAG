# Contributing to AtlasRAG

Read [IDEA.md](IDEA.md) first — it holds the design, the nine-phase plan, and the rationale
behind every stack decision. This file only covers *how to work in the repo*.

The project's rule of thumb: **nothing improves until it's measured**. A change that claims
a quality gain without a number from `evals/reports/` is not done yet.

## Setup

```bash
uv sync --all-extras --dev
cp .env.example .env          # fill in the keys
uv run pre-commit install
make dev                      # postgres+pgvector, redis, langfuse
make migrate
```

Requires Python ≥ 3.12, `uv`, and Docker.

## Before you push

```bash
make check     # lint + typecheck + module boundaries + tests
```

CI runs the same thing, plus a frontend build and the eval gate. If `make check` is green
locally, CI should be too.

| Command | What it enforces |
|---|---|
| `make lint` | ruff check + format |
| `make typecheck` | mypy strict over `src apps evals scripts` |
| `make arch` | import-linter — the module boundary rules below |
| `make test` | pytest |

## Architecture rules

The dependency direction is **`apps → modules → platform → contracts`**, and it is enforced
by import-linter (`[tool.importlinter]` in `pyproject.toml`), not by good intentions:

- **`contracts/`** is the shared vocabulary — answer, citation, conflict, retrieval, events.
  It imports nothing from the rest of the codebase. Changing a contract is a cross-cutting
  change: say so in the PR description.
- **`platform/`** holds technical capabilities behind interfaces (Protocol/ABC): database,
  cache, parsing, embeddings, reranking, llm, observability, security, queue. **Every
  external component sits behind an interface** — that is what turns "swap pgvector for
  Qdrant" into two lines. A concrete vendor SDK (`openai`, `cohere`, `docling`) may only be
  imported inside its own platform package.
- **`modules/`** hold business capabilities. **Modules never import each other.** If
  `answering` needs something from `documents`, the shared piece belongs in `contracts/`, or
  it travels as an event.
- **`apps/`** are entrypoints: wiring, routing, serialization. No domain logic — if you're
  tempted to write a rule in `apps/api/router.py`, it belongs in a module.

New third-party dependency, new persistence choice, or a change to the answer contract →
write an ADR in `docs/adr/` (`NNNN-short-title.md`: context, decision, consequences,
alternatives) and link it from the PR.

## Tests

Markers are declared in `pyproject.toml`; put the test in the directory matching its marker.

| Marker | Directory | Needs |
|---|---|---|
| `unit` | `tests/unit` | nothing external — pure logic (RRF, chunkers, Arabic normalization, status decisions) |
| `integration` | `tests/integration` | Postgres/Redis via testcontainers |
| `e2e` | `tests/e2e` | the full stack via docker compose |
| `architecture` | `tests/architecture` | import-linter contracts |

Two categories of test are **non-negotiable** and must never be weakened to make a build
pass — they're the ones that decide whether this system could ship in a company:

1. **ACL.** Filtering happens *inside* the retrieval query (a SQL condition on
   `allowed_roles`), never as a post-filter after generation. Any change to retrieval needs
   a test proving a user without the role cannot surface the chunk.
2. **The answer contract.** Every response carries exactly one of `answered`,
   `insufficient_evidence`, `conflicting_evidence`, `access_restricted`, `out_of_scope`.
   Refusal and conflict detection are features with their own tests, not edge cases.

## Changes that touch quality

Any change to parsing, chunking, embeddings, retrieval, reranking, prompts, or the graph:

```bash
make eval      # writes evals/reports/<timestamp>-<sha>.json + .md
```

Paste the before/after table into the PR, always broken down **overall / EN / AR**. An
aggregate number hides the collapse of an entire language, and Arabic is a first-class
target here, not a bonus.

A negative result is a good contribution. "I tried HyDE, measured it, it added nothing, I
removed it" belongs in `docs/adr/` — that's a finding, not a failure.

The eval gate in CI compares against `evals/reports/baseline.json`. If a PR intentionally
moves the baseline, update that file in the same PR and explain why.

## Data and the corpus

- The corpus keeps **30–40% Arabic** content. Adding documents shouldn't drift that share.
- Planting a conflict: put the contradiction in two real documents, register it in
  `evals/datasets/planted_conflicts.md`, and add golden questions with
  `expected_status: conflicting_evidence` that reference its `id`. That file is the ground
  truth for conflict-detection recall — keep it accurate.
- Golden questions are `{question, ground_truth_answer, source_chunk_ids, category, lang,
  expected_status}` in JSONL under `evals/datasets/golden/`.
- Never commit real company documents, credentials, or `.env`. Only synthetic or public
  material goes in `corpus/`.

## Migrations

```bash
make revision m="add document_versions"   # autogenerate
make migrate                              # apply
```

Review the generated SQL before committing — autogenerate misses `pgvector` index options
and `tsvector` triggers. Migrations are forward-only in production; write a real
`downgrade()` anyway for local work.

## Commits and PRs

Conventional commits, imperative mood:

```
feat(retrieval): add RRF fusion over dense + lexical
fix(ingestion): keep original text when normalizing Arabic for the index
docs(adr): record why HyDE was removed
```

Scopes follow the layout: `api`, `worker`, `identity`, `documents`, `ingestion`,
`retrieval`, `answering`, `conversations`, `feedback`, `platform`, `evals`, `infra`, `docs`.

Branch off `main` (`feat/…`, `fix/…`, `docs/…`), keep PRs to one phase-sized change, and in
the description say: what changed, which numbers moved (with the report), and which ADR
covers the decision.
