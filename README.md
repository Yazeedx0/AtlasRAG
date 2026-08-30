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
make dev                      # postgres+pgvector and Keycloak
make migrate
make ingest
make eval                     # writes a report to evals/reports/
```

### Seed the demo company and get a CLI token

Apply the migrations, then seed the Atlas Corp demo company in Keycloak and AtlasRAG:

```bash
make migrate
export ATLAS_SEED_USER_PASSWORD='use-a-local-development-password'
make seed-dev
```

The seed creates the configured admin user plus seven demo users, six roles, six groups,
role assignments, nested group memberships, six sample documents, and document ACLs.
All seeded Keycloak users use the password supplied through `ATLAS_SEED_USER_PASSWORD`.
The script is safe to rerun: it reuses existing Keycloak users and local identities and
reconciles the seeded records without deleting data. Use `--reset-password` only when you
explicitly want to reset the existing demo users' password.
The Keycloak admin password must be configured in `.env` or supplied with
`ATLAS_KEYCLOAK_ADMIN_PASSWORD`.

With the default configuration, the seeded usernames are `atlas-admin`,
`alice.engineer`, `bob.engineer`, `carol.hr`, `diana.hr`, `eric.finance`,
`fatima.finance`, and `george.operations`.

The seed also ensures the development-only `atlasrag-cli` client. Get a token for Postman
or other local API clients with:

```bash
uv run python -m scripts.get_dev_token
```

Copy the printed value into Postman's Bearer Token authorization. This client uses the
password grant for local development only; the `atlasrag-web` client remains an
authorization-code client.

To remove only the seeded demo company from the database and Keycloak while preserving
the schema and migration-owned permissions:

```bash
make clean-seed
```

This removes the seeded demo users, roles, groups, documents, memberships, assignments,
ACLs, and the development-only `atlasrag-cli` client. It does not delete Docker volumes.

### Authentication

Local authentication uses Keycloak. Start the database and Keycloak services with:

```bash
docker compose -f infra/docker-compose.yml up -d postgres keycloak
```

Keycloak is available at <http://localhost:8080>. The imported realm is `atlasrag`, with
the API client `atlasrag-api`; configuration and admin instructions are documented in
[`infra/keycloak/README.md`](infra/keycloak/README.md).

Protected FastAPI routes can use the reusable
`get_authenticated_identity` dependency from
[`apps/api/dependencies/authentication.py`](apps/api/dependencies/authentication.py).
It verifies the bearer token and returns `AuthenticatedIdentity`. Mapping that external
identity to a local AtlasRAG Principal remains the responsibility of `IdentityResolver`.

AtlasRAG is a stateless resource server: it intentionally does not implement login,
OIDC callbacks, logout, refresh-token handling, or browser session persistence. Keycloak
owns the authentication lifecycle, and the frontend/BFF obtains the access token and sends
it to the API. The API is responsible for token verification, local identity resolution,
and AtlasRAG authorization.

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
