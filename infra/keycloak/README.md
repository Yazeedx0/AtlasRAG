# Keycloak

This directory contains the local development realm configuration for AtlasRAG.

## Configuration

- Realm: `atlasrag`
- API client: `atlasrag-api` (bearer-only)
- Web client: `atlasrag-web` (public OIDC client)
- Web redirect URI: `http://localhost:3000/*`
- Web registration: enabled for local development
- Keycloak URL: <http://localhost:8080>
- Realm issuer: <http://localhost:8080/realms/atlasrag>
- Database: `keycloak` with the dedicated `keycloak` database user

The client configuration is embedded in [`atlasrag-realm.json`](./atlasrag-realm.json). Keycloak
imports this file automatically when the Compose service starts with `--import-realm`.

## Admin console

Open <http://localhost:8080/admin> and sign in with the values configured by:

```text
ATLAS_KEYCLOAK_ADMIN_USERNAME
ATLAS_KEYCLOAK_ADMIN_PASSWORD
```

The development defaults are `admin` / `admin`. Change them in `.env` for local use; these
defaults must not be used in production.

## Start Keycloak

From the repository root:

```bash
docker compose -f infra/docker-compose.yml up -d postgres keycloak
```

Realm import only creates the realm when it does not already exist. To re-import the export,
remove the local Compose volumes and start the services again:

```bash
docker compose -f infra/docker-compose.yml down -v
docker compose -f infra/docker-compose.yml up -d postgres keycloak
```

The `down -v` command deletes local development database data.

The AtlasRAG application and Keycloak use separate databases and database users on the
same Postgres server. The Postgres initialization hook creates the Keycloak database and
role on the first initialization of the `postgres_data` volume.

## API authentication

The verifier is created during application startup by
[`src/atlasrag/bootstrap/lifespan.py`](../../src/atlasrag/bootstrap/lifespan.py). It uses
the configured issuer and audience, discovers the realm JWKS endpoint, caches signing
keys, and refreshes them in a bounded manner.

Protect an API route with the authentication dependency:

```python
from typing import Annotated

from fastapi import Depends

from apps.api.dependencies.authentication import get_authenticated_identity
from atlasrag.contracts.authentication import AuthenticatedIdentity


CurrentIdentity = Annotated[
    AuthenticatedIdentity,
    Depends(get_authenticated_identity),
]
```

The dependency authenticates the external identity only. Use `IdentityResolver` in the
application/service layer to resolve `(issuer, subject)` to an AtlasRAG Principal and to
enforce local disabled or retired identity rules.

The first protected integration endpoint is:

```text
GET /api/v1/auth/me
```

It verifies the bearer token and resolves the identity to a local Principal. Local
just-in-time provisioning is controlled by `ATLAS_IDENTITY_JIT_ENABLED` and is enabled by
default for local development. Set it to `false` when local users must be provisioned by an
explicit administrative workflow:

```text
ATLAS_IDENTITY_JIT_ENABLED=false
```

The `atlasrag-web` client adds `atlasrag-api` to the access-token audience through a protocol
mapper, which allows the API verifier to enforce its configured audience.
