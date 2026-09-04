# AtlasRAG

Enterprise knowledge infrastructure: a modular monolith for storing, authorizing, and
(eventually) retrieving company documents, built around document-level access control,
explicit document lifecycle, and provider-neutral infrastructure boundaries.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)

AtlasRAG is not "a chatbot over PDFs." It is being built as the access-control and
document-lifecycle backbone a real enterprise RAG system needs before retrieval quality
even matters: who a caller really is, what they are allowed to read, and how a document's
bytes, versions, and derived data relate to one another. Retrieval, ingestion, and answer
generation are being built on top of that foundation and are not yet complete — see
[Project status](#project-status) for exactly what exists today.

## Key characteristics

- **Authentication/authorization split** — Keycloak proves external identity; AtlasRAG owns
  local identity, roles, groups, and document authorization.
- **Document/version/artifact separation** — a logical `Document` is not a `DocumentVersion`,
  and a version is not the physical file behind it.
- **Two independent authorization planes** — capability-based control-plane permissions
  (`iam.*.manage`, `knowledge.*.manage`) are separate from data-plane document ACL grants.
- **Temporal, allow-only ACL** — document access grants are additive and time-bounded, never
  deny rules, and are retained as history when revoked.
- **Object storage behind a contract** — the application depends on an `ObjectStorage`
  protocol, not the MinIO SDK.
- **PostgreSQL as the system of record** — `iam` and `knowledge` schemas today, with `rag`
  and `audit` schemas designed but not yet migrated.
- **Provider-neutral AI adapters** — `TextGenerator`, `Embedder`, and `Reranker` contracts
  with OpenAI, Anthropic, Cohere, and Gemini implementations behind them.

## Project status

Implementation status is derived from the code in this repository, not from design
documents. Design intent that has no corresponding implementation is marked planned.

| Area | Status | Notes |
|---|---|---|
| Platform foundation | ✅ Implemented | FastAPI app, async SQLAlchemy 2.0 + Alembic, `contracts → platform → modules → bootstrap → apps` dependency direction enforced by import-linter |
| Authentication | ✅ Implemented | Keycloak OIDC bearer-token verification, JWKS caching with bounded refresh, stateless resource server (no login/session/refresh endpoints by design) |
| Local identity | ✅ Implemented | `Principal` / `User` / `UserIdentifier` model, JIT provisioning, principal activate/deactivate/retire lifecycle |
| Effective-principal resolution | ✅ Implemented | Direct roles + direct and nested group membership, resolved for authorization |
| IAM authorization (control plane) | ✅ Implemented | Capability grants (e.g. `knowledge.documents.manage`) gate admin/API routes; superadmin policy |
| Documents & versions | ✅ Implemented | Document CRUD, version lifecycle (`draft → published → withdrawn/archived`) with non-overlapping effective date ranges |
| Document artifacts | ✅ Implemented | Multipart upload to a draft version, SHA-256 hashing, size limits, MinIO-backed storage |
| Document ACL (data plane) | ✅ Implemented | Temporal, allow-only `read`/`manage` grants per principal, independent of control-plane capabilities |
| Ingestion orchestration schema | 🚧 In progress | `ingestion_runs` / `ingestion_items` model claim/lease/heartbeat and single-active-item promotion; no parsing/chunking pipeline wired to it yet |
| AI provider adapters | 🚧 In progress | Generation/embedding/reranking contracts with OpenAI, Anthropic, Cohere, Gemini clients exist; not yet called from any retrieval or ingestion flow |
| Chunking & embedding storage | 📋 Planned | `knowledge.chunks`, `embedding_models`, `chunk_embeddings` are designed (see [schema overview](docs/diagrams/schema-overview.md)); no migrations exist yet |
| Retrieval | 📋 Planned | Hybrid dense/lexical retrieval and reranking are design-stage only |
| Answer contract / agentic serving | 📋 Planned | `rag` schema (conversations, answer runs, citations, conflicts, feedback) is design-stage only |
| Background worker | 📋 Planned | `apps/worker` is a scaffolded package with no implementation |
| Evaluation harness | 📋 Planned | No `evals/` implementation exists in the repository |
| Observability | 📋 Planned | No tracing/metrics wired into the application |
| CI/CD | 📋 Planned | No GitHub Actions workflows exist in the repository |

## Why AtlasRAG exists

A naive RAG project looks like:

```text
upload file → split text → embed → nearest-neighbor search → LLM
```

That pipeline has no concept of who is asking, whether a document changed since it was
indexed, or whether two chunks came from the same physical file. AtlasRAG treats those as
first-class engineering problems to solve *before* retrieval quality is worth measuring:

- **Identity** — an external OIDC subject is not a durable application identity.
- **Authorization** — access must be resolved before restricted content can enter retrieval
  or an LLM context window, not filtered out afterward.
- **Document lifecycle** — a policy document has versions, effective dates, and can be
  withdrawn; "the file" and "the document" are different lifetimes.
- **Reproducible derived data** — ingestion output (chunks, embeddings) must be
  regenerable from the canonical artifact without reinterpreting business rules.
- **Provider neutrality** — object storage, token verification, and AI providers sit behind
  contracts so the vendor behind them can change without rewriting application code.

## Architecture

```mermaid
flowchart TB
    Client[Client / API caller] -->|OIDC login| Keycloak
    Client -->|Bearer access token| API[AtlasRAG API — FastAPI]
    Keycloak -->|verified JWT claims| API

    subgraph API_internal[" "]
        direction TB
        Auth[TokenVerifier] --> Identity[Identity: Principal /\neffective principals]
        Identity --> Authz[IAM capability checks +\nDocument ACL]
        Authz --> Knowledge[Knowledge: Documents /\nVersions / Artifacts]
    end

    API --> API_internal
    Knowledge --> Postgres[(PostgreSQL\niam + knowledge schemas)]
    Knowledge --> MinIO[(MinIO\nobject storage)]

    Knowledge -.->|planned| Ingestion[Ingestion pipeline]
    Ingestion -.->|planned| Retrieval[Hybrid retrieval + reranking]
    Retrieval -.->|planned| Answering[Answer contract / agentic serving]
```

Solid arrows are implemented; dashed arrows are designed but not yet built. `apps/api` is
wiring only — routing, request/response schemas, and dependency injection. Business rules
live in `src/atlasrag/modules`, technical integrations live behind contracts in
`src/atlasrag/platform`, and `src/atlasrag/bootstrap` composes the two at startup.

## Security model

Authentication and authorization are deliberately separate concerns, documented in detail
in the [authentication integration contract](docs/adr/keycloak/authentication-integration-contract.md)
and the [identity architecture](docs/adr/keycloak/identity-architecture.md).

```mermaid
flowchart TB
    Token[Bearer access token] --> Verify[Keycloak TokenVerifier\nsignature, issuer, audience, expiry]
    Verify --> AuthIdentity[AuthenticatedIdentity\nissuer + subject]
    AuthIdentity --> Resolve[IdentityResolver\nissuer+subject → local Principal]
    Resolve --> Effective[Effective principals\nuser + roles + nested groups]
    Effective --> Control[Control plane:\nIAM capability checks]
    Effective --> Data[Data plane:\nDocument ACL grants]
    Control --> Admin[Admin / management routes]
    Data --> Docs[Document content access]
```

- **Keycloak proves who the caller is.** AtlasRAG never stores passwords and does not
  implement login, OIDC callbacks, logout, or refresh-token handling — it is a stateless
  resource server that only verifies bearer tokens.
- **AtlasRAG owns what the caller may do.** The Keycloak `sub` claim is never used as the
  durable identity key; `(issuer, subject)` resolves to a stable local `Principal` through
  `iam.user_identifiers`. A newly provisioned user receives zero roles, zero groups, and
  zero document grants — authentication never implies authorization.
- **Two distinct authorization planes.** IAM capabilities (`iam.principals.manage`,
  `knowledge.documents.manage`, …) gate management operations; they do not grant document
  content access. Document content access is controlled exclusively by active Document ACL
  grants. A superadmin capability does not bypass document ACL.
- **Fail closed.** Keycloak roles/groups are not treated as document authorization inputs.
  Document ACL filtering is designed to happen before restricted content can reach
  retrieval or an LLM context — never as a post-filter.

## Knowledge model

```text
Document                              (logical policy, e.g. "Remote Work Policy")
└── DocumentVersion                   (draft → published → withdrawn/archived,
    │                                   non-overlapping effective date ranges)
    └── DocumentArtifact              (one physical file: PDF, DOCX, HTML, Markdown, text)
        └── object storage (MinIO)    (bytes, addressed by a storage key + SHA-256 hash)
```

Example: a "Remote Work Policy" document might have a published `v1` version with an
English and an Arabic PDF artifact, and a draft `v2` version with an updated English PDF
awaiting publication. These are separate concepts because they have separate lifetimes: the
document is durable, a version is effective for a date range, and an artifact is one
physical rendering of that version — the application depends on an `ObjectStorage` contract
rather than the MinIO SDK directly, so the physical backend can change independently of the
document model.

## Repository structure

```text
apps/
├── api/                  FastAPI entrypoint: routes, request/response schemas, DI wiring
│   ├── routes/iam/       principals, roles, groups, permissions, authentication
│   └── routes/knowledge/ documents, document versions, document artifacts
└── worker/               scaffolded background-worker entrypoint (not yet implemented)

src/atlasrag/
├── contracts/            shared vocabulary: Protocol interfaces + DTOs, no dependencies
│                         on the rest of the codebase (authentication, authorization,
│                         permissions, documents, object storage, AI capabilities)
├── modules/               business capabilities
│   ├── identity/          principals, roles, groups, effective-principal resolution
│   ├── knowledge/          documents, versions, artifacts, document ACL
│   └── ingestion/          ingestion run/item models (orchestration schema only)
├── platform/               technical capabilities behind the contracts above
│   ├── auth/keycloak.py    Keycloak TokenVerifier adapter
│   ├── database/           SQLAlchemy engine/session/base
│   ├── storage/minio.py    ObjectStorage adapter
│   └── ai/                 generation/embedding/reranking adapters (OpenAI, Anthropic,
│                            Cohere, Gemini) behind TextGenerator/Embedder/Reranker
└── bootstrap/              settings, DI composition, FastAPI lifespan wiring

migrations/versions/    Alembic migrations, sequential zero-padded IDs (0001, 0002, …)
docs/                    ADRs, architecture notes, diagrams, API reference
bruno/                   Bruno HTTP collection mirroring the implemented API surface
tests/                   unit, integration (testcontainers), e2e (scaffolded)
```

The dependency direction is `apps/bootstrap → modules → platform → contracts`. Modules
never import each other; `contracts/` has no dependency on the rest of the codebase, and
every external system (Keycloak, MinIO, AI providers) is reached only through a `platform/`
adapter implementing a `contracts/` interface.

## Tech stack

| Concern | Technology | Role |
|---|---|---|
| Language / tooling | Python 3.12, `uv` | Runtime and dependency management |
| API | FastAPI, Uvicorn | Async HTTP layer |
| Validation / config | Pydantic v2, pydantic-settings | Request/response schemas, typed environment-backed settings |
| Persistence | SQLAlchemy 2.0 (async), asyncpg | ORM and database driver |
| Migrations | Alembic | Sequential, numerically-versioned schema migrations |
| Database | PostgreSQL, pgvector extension | System of record; `pgvector` and `btree_gist` extensions are provisioned for future vector search and version exclusion constraints |
| Authentication | Keycloak (OIDC/OAuth2), PyJWT | External identity provider and JWT verification |
| Object storage | MinIO, `aioboto3` (S3 API) | Document artifact bytes, behind an `ObjectStorage` contract |
| AI providers | OpenAI, Anthropic, Cohere, Google Gemini SDKs | Generation, embedding, and reranking adapters |
| Testing | pytest, pytest-asyncio, testcontainers | Unit and Postgres-backed integration tests |
| Quality gates | ruff, mypy (strict), import-linter | Lint/format, static typing, module-boundary enforcement |

`litellm`, `langgraph`, `redis`, `arq`, `langfuse`, and `docling` are declared as project
dependencies for the retrieval/ingestion/observability work described in
[docs/IDEA.md](docs/IDEA.md), but nothing in the current codebase imports them yet.

## Getting started

Prerequisites: Python ≥ 3.12, [`uv`](https://docs.astral.sh/uv/), Docker with Compose.

```bash
uv sync --all-extras --dev
cp .env.example .env                  # fill in provider keys as needed
echo 'ATLAS_DATABASE_URL=postgresql+asyncpg://atlas:atlas_dev_password@localhost:5432/atlasrag' >> .env
make dev                              # postgres+pgvector, keycloak, minio
make migrate                          # apply Alembic migrations
```

`ATLAS_DATABASE_URL` is required by `Settings` but is not included in `.env.example`; set it
explicitly, matching the Postgres credentials in `.env`.

`make dev` starts every service defined in `infra/docker-compose.yml`: PostgreSQL
(with the Keycloak database provisioned alongside it), Keycloak (importing the local
`atlasrag` realm automatically), and MinIO plus a one-shot `minio-init` job that creates
the configured bucket.

### Seed a demo company

```bash
export ATLAS_SEED_USER_PASSWORD='use-a-local-development-password'
make seed-dev
```

This creates the configured admin user, seven demo users, six roles, six groups, role
assignments, nested group memberships, six sample documents, and document ACL grants — both
in Keycloak and in the AtlasRAG database. It is safe to rerun. Remove it with:

```bash
make clean-seed
```

### Run the API

```bash
make run-dev      # uvicorn with reload, http://localhost:8000
```

Interactive API docs are served at `/docs`; the versioned application surface lives under
`/api/v1`, while `/health` and `/health/ready` are intentionally unversioned. See
[docs/API.md](docs/API.md) for the full endpoint reference.

### Get a local bearer token

```bash
uv run python -m scripts.get_dev_token
```

Prints an access token for the seeded development user via the password grant, for use
against `/docs` or a local HTTP client — this client exists only for local development.

## Configuration

Settings are loaded from the environment with the `ATLAS_` prefix (see
`src/atlasrag/bootstrap/core/config.py` and `.env.example`). Secrets are omitted below.

| Variable | Description | Example |
|---|---|---|
| `ATLAS_DISABLE_AUTH` | Bypass token verification (local development only) | `false` |
| `ATLAS_DATABASE_URL` | PostgreSQL connection string — required, not present in `.env.example` | `postgresql+asyncpg://atlas:...@localhost/atlasrag` |
| `ATLAS_KEYCLOAK_ISSUER` | Trusted OIDC issuer | `http://localhost:8080/realms/atlasrag` |
| `ATLAS_KEYCLOAK_AUDIENCE` | Expected access-token audience | `atlasrag-api` |
| `ATLAS_KEYCLOAK_ALGORITHMS` | Accepted JWT signing algorithms | `["RS256"]` |
| `ATLAS_KEYCLOAK_JWKS_CACHE_TTL_SECONDS` | JWKS signing-key cache TTL | `3600` |
| `ATLAS_IDENTITY_JIT_ENABLED` | Just-in-time local user provisioning | `true` |
| `ATLAS_MINIO_ENDPOINT_URL` | MinIO / S3 endpoint | `http://localhost:9000` |
| `ATLAS_MINIO_BUCKET` | Default artifact bucket | `atlasrag` |
| `ATLAS_MAX_FILE_SIZE_BYTES` | Maximum artifact upload size | `52428800` |
| `ATLAS_GENERATION_PROVIDER` / `ATLAS_EMBEDDING_PROVIDER` / `ATLAS_RERANK_PROVIDER` | AI capability provider selection (`openai`, `anthropic`, `cohere`, `gemini`) | `openai` |
| `ATLAS_OPENAI_API_KEY`, `ATLAS_ANTHROPIC_API_KEY`, `ATLAS_COHERE_API_KEY`, `ATLAS_GEMINI_API_KEY` | Provider credentials | — |

## Authentication development setup

AtlasRAG verifies Keycloak access tokens and resolves `(issuer, subject)` to a local
`Principal`; it does not implement its own login or session state. Start Keycloak with:

```bash
docker compose -f infra/docker-compose.yml up -d postgres keycloak
```

The `atlasrag` realm, the `atlasrag-api` resource-server client, and the confidential
`atlasrag-web` client are imported automatically. See
[`infra/keycloak/README.md`](infra/keycloak/README.md) for admin console access and how to
protect a FastAPI route with `get_authenticated_identity`.

## Database

PostgreSQL is organized into schemas by responsibility. Only `iam` and `knowledge` have
migrations today; `rag` and `audit` are designed (see
[docs/diagrams/schema-overview.md](docs/diagrams/schema-overview.md)) but not yet created.

| Schema | Holds | Status |
|---|---|---|
| `iam` | Principals, users, identifiers, roles, groups, role/group assignments | ✅ Implemented |
| `knowledge` | Documents, versions, artifacts, document ACL, ingestion runs/items | ✅ Implemented (chunks/embeddings tables not yet added) |
| `rag` | Conversations, answer runs, citations, conflicts, feedback | 📋 Planned |
| `audit` | Security and operational audit events | 📋 Planned |

Schema separation keeps identity/authorization data, document/knowledge data, and future
conversational/answer data independently evolvable. See the schema overview doc for full
table inventories and referential-action decisions.

## Development commands

| Command | What it does |
|---|---|
| `uv sync --all-extras --dev` | Install dependencies |
| `make dev` / `make docker-down` | Start / stop the local Postgres, Keycloak, and MinIO stack |
| `make migrate` | Apply Alembic migrations |
| `make revision m="..."` | Autogenerate a migration (rename/renumber per [CLAUDE.md](CLAUDE.md) before committing) |
| `make run-dev` | Run the API with reload |
| `make seed-dev` / `make clean-seed` | Seed / remove the demo company |
| `make lint` / `make fmt` | ruff check / apply fixes and formatting |
| `make typecheck` | mypy strict over `src apps` |
| `make arch` | Enforce module boundaries via import-linter |
| `make test` | Run the pytest suite |
| `make check` | lint + typecheck + arch + test |

## Testing strategy

```text
tests/unit/          pure logic — no external services
tests/integration/   Postgres-backed, via testcontainers (identity, knowledge, API)
tests/e2e/           scaffolded, not yet implemented
```

Integration coverage includes identity provisioning races, effective-principal resolution
over nested groups, the permission engine, document artifact upload, document version
lifecycle transitions, and the authenticated-principal request flow end to end. Unit tests
cover service-level branching (permission authorization, principal lifecycle, role
assignment, superadmin policy, document authorization) and the AI provider adapters.

## Engineering principles

1. **Authorization before content access.** Document ACL is designed to gate retrieval, not
   filter results after the fact.
2. **External systems behind contracts.** Keycloak, MinIO, and every AI provider are reached
   through a `Protocol` in `contracts/`, implemented in `platform/`.
3. **Canonical source vs. derived representations.** A `DocumentArtifact` is the physical
   source of truth; ingestion output is reproducible derived data.
4. **Stable local identity.** The external IdP's subject identifier is never the durable
   application identity.
5. **Explicit lifecycle transitions.** Document versions and principals expose named state
   transitions (`publish`, `withdraw`, `archive`, `activate`, `deactivate`, `retire`)
   instead of generic field updates.
6. **Temporal, not destructive, authorization state.** Role assignments, group memberships,
   and ACL grants are revoked, not deleted, and remain as history.
7. **Fail closed.** New principals get zero roles, zero groups, and zero document grants by
   default.
8. **Two independent authorization planes.** Control-plane capabilities and data-plane
   document ACL are never conflated.

## Roadmap

**Implemented:** identity and authentication (Keycloak), IAM capability authorization,
document/version/artifact model, document ACL, object storage behind a contract, ingestion
orchestration schema, AI provider adapters.

**In progress:** wiring the ingestion pipeline (parsing, chunking) to the existing
`ingestion_runs`/`ingestion_items` schema; wiring the AI provider adapters into an actual
capability path.

**Planned, in rough order:** chunk and embedding storage (`knowledge.chunks`,
`embedding_models`, `chunk_embeddings`), hybrid dense/lexical retrieval with reranking, the
`rag` schema and answer contract, a background worker for ingestion execution, an
evaluation harness, observability, and CI/CD. See [docs/IDEA.md](docs/IDEA.md) for the full
original design rationale and phased plan; the implemented architecture has since evolved
from that document's original module layout, and this README reflects the current code.

## Documentation

- [docs/API.md](docs/API.md) — HTTP endpoint reference
- [docs/adr/keycloak/authentication-integration-contract.md](docs/adr/keycloak/authentication-integration-contract.md) — the `TokenVerifier` contract
- [docs/adr/keycloak/identity-architecture.md](docs/adr/keycloak/identity-architecture.md) — identity, provisioning, and the authorization hand-off
- [docs/diagrams/schema-overview.md](docs/diagrams/schema-overview.md) — database schema map and model invariants
- [docs/diagrams/schema-erd.png](docs/diagrams/schema-erd.png) / [docs/diagrams/auth-keycloak.md](docs/diagrams/auth-keycloak.md) — entity-relationship and auth-flow diagrams
- [infra/keycloak/README.md](infra/keycloak/README.md) — local Keycloak realm configuration
- [docs/IDEA.md](docs/IDEA.md) — original end-to-end design and phased build plan

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the local development workflow, the pre-push
checks (`make check`), and the module-boundary and migration-numbering rules. In short:
branch off `main`, keep the `contracts → platform → modules` dependency direction, write a
migration per [CLAUDE.md](CLAUDE.md)'s numbering scheme for schema changes, and add tests
for the layer you touched.

## License

[MIT](LICENSE)
