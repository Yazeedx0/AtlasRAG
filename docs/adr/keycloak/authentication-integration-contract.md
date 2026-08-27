# AtlasRAG Authentication Integration Contract

**Status:** v1 contract  
**Provider implementation:** Keycloak  
**Contract owner:** `src/atlasrag/contracts/authentication.py`  
**Provider adapter:** `src/atlasrag/platform/auth/keycloak.py`

**Implementation status:** The Keycloak verifier, bootstrap lifecycle wiring, and FastAPI
bearer-token dependency are implemented. Local identity resolution remains a separate
application-service step for protected business routes.

---

## 1. Objective

This contract isolates AtlasRAG application code from Keycloak-specific token-verification details.

The contract converts an untrusted bearer token into a small trusted identity object.

```text
Bearer token
    |
    v
TokenVerifier contract
    |
    +-- implementation: KeycloakTokenVerifier
    |
    v
AuthenticatedIdentity
    |
    v
IdentityResolver / local identity logic
```

The contract deliberately does **not** perform document authorization, role traversal, group traversal, or local user provisioning itself.

---

## 2. Canonical Python Contract

```python
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    issuer: str
    subject: str
    email: str | None = None
    email_verified: bool | None = None
    username: str | None = None
    display_name: str | None = None


class TokenVerificationError(Exception):
    """Raised when an authentication token cannot be trusted."""


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> AuthenticatedIdentity:
        """Verify a token and return a trusted external identity."""
        ...
```

---

## 3. Contract Semantics

### Input

`token: str`

The input is the raw bearer access token value, without the `Bearer ` prefix.

The caller is responsible for extracting the HTTP Authorization header and passing only the token string.

### Success

On successful verification, `verify()` returns an immutable `AuthenticatedIdentity`.

At this point:

- signature is trusted;
- token timing is valid;
- issuer is trusted;
- audience/client validation passed according to configured policy;
- required identity claims are present;
- `issuer` and `subject` may be used for local identity resolution.

### Failure

Any condition that makes the token untrustworthy must raise `TokenVerificationError` or a project-level subclass.

Provider/library-specific exceptions must be translated at the adapter boundary.

Examples:

```text
bad signature
unknown signing key that cannot be refreshed
wrong issuer
wrong audience
expired token
not-yet-valid token
missing subject
missing issuer
malformed token
unsupported signing algorithm according to local policy
```

The contract should not expose Keycloak-client or JWT-library exception types to Identity application code.

---

## 4. Trusted Identity Fields

### `issuer`

Required.

Source:

```text
OIDC `iss`
```

Used as part of the durable external-identity key.

### `subject`

Required.

Source:

```text
OIDC `sub`
```

Used together with issuer:

```text
(issuer, subject)
```

`subject` alone is not globally unique across different issuers.

### `email`

Optional convenience/profile field.

It must not be used as the primary identity key.

### `email_verified`

Optional provider assertion.

Its presence does not replace AtlasRAG authorization checks.

### `username`

Optional convenience/profile field, typically mapped from a configured OIDC claim such as `preferred_username`.

It is not a stable authorization identifier.

### `display_name`

Optional convenience/profile field, typically mapped from `name` or another configured claim.

It may be used during provisioning/profile refresh according to application policy.

---

## 5. Fields Explicitly Excluded from the Contract

The v1 `AuthenticatedIdentity` does not expose:

- Keycloak realm roles;
- Keycloak client roles;
- Keycloak groups;
- refresh tokens;
- session IDs;
- raw JWT claims map;
- authorization decisions;
- AtlasRAG Principal ID.

Reason: authentication and AtlasRAG authorization are intentionally separated.

---

## 6. Keycloak Adapter Responsibilities

`KeycloakTokenVerifier` lives in infrastructure/platform code.

Implemented location:

```text
src/atlasrag/platform/auth/keycloak.py
```

The verifier is constructed by:

```text
src/atlasrag/bootstrap/lifespan.py
```

FastAPI routes authenticate requests through:

```text
apps/api/dependencies/authentication.py:get_authenticated_identity
```

It is responsible for:

1. reading configured Keycloak/OIDC settings;
2. obtaining signing keys/JWKS;
3. validating token signature;
4. validating algorithm policy;
5. validating issuer;
6. validating audience/client according to AtlasRAG configuration;
7. validating expiration and applicable time claims;
8. extracting required claims;
9. mapping claims to `AuthenticatedIdentity`;
10. translating provider/JWT exceptions to `TokenVerificationError`.

It is **not** responsible for:

- opening application database transactions;
- creating local users;
- role/group resolution;
- document authorization;
- HTTP response formatting.

---

## 7. JWKS / Signing-Key Behavior

The implementation should use Keycloak's published OIDC metadata/JWKS rather than hard-coding an individual public key into application code.

Operational expectations:

- signing keys are cached;
- cache has a bounded refresh policy;
- an unknown `kid` may trigger one controlled metadata/JWKS refresh;
- repeated unknown keys must not create an unbounded network retry loop;
- the implementation must fail closed when signature trust cannot be established.

The current adapter uses an async HTTP client, caches signing keys for a configured TTL,
and allows one controlled refresh for an unknown `kid` subject to a refresh cooldown.
The exact cache mechanism belongs to the Keycloak adapter, not the contract.

---

## 8. Configuration Contract

The adapter should receive configuration through AtlasRAG settings/bootstrap, not read arbitrary environment variables throughout the module.

Expected conceptual settings:

```text
keycloak_issuer
keycloak_audience / client_id policy
OIDC discovery or JWKS location derived from issuer where possible
allowed algorithms
network timeout
JWKS cache/refresh settings
```

The current environment-backed settings are:

```text
ATLAS_KEYCLOAK_ISSUER
ATLAS_KEYCLOAK_AUDIENCE
ATLAS_KEYCLOAK_ALGORITHMS
ATLAS_KEYCLOAK_TIMEOUT_SECONDS
ATLAS_KEYCLOAK_JWKS_CACHE_TTL_SECONDS
ATLAS_KEYCLOAK_JWKS_REFRESH_COOLDOWN_SECONDS
```

Secrets should only be required when the chosen OIDC flow actually requires them. Verifying a public-key-signed access token should not require embedding a realm private key in AtlasRAG.

---

## 9. Identity Resolution Contract

Token verification ends at `AuthenticatedIdentity`.

A separate application service resolves it to the local identity model.

Recommended conceptual interface:

```python
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ResolvedUserIdentity:
    user_principal_id: UUID


class IdentityResolver(Protocol):
    async def resolve(
        self,
        identity: AuthenticatedIdentity,
    ) -> ResolvedUserIdentity:
        ...
```

The real implementation may later return additional immutable fields when genuinely needed, but the local Principal ID is the critical hand-off.

Resolution rule:

```text
AuthenticatedIdentity.issuer
AuthenticatedIdentity.subject
        |
        v
active iam.user_identifiers row:
  identifier_type = oidc_subject
  issuer = identity.issuer
  normalized_value = identity.subject
        |
        v
User / Principal
```

---

## 10. Provisioning Contract

If no active local identity exists, the configured provisioning policy decides the next action.

### JIT provisioning policy

When enabled:

```text
verified external identity
    |
    v
no active local identifier
    |
    v
atomic local provisioning transaction
```

Transaction:

```text
Principal(type=user)
User(principal_id=same Principal ID)
UserIdentifier(
  identifier_type=oidc_subject,
  issuer=<iss>,
  normalized_value=<sub>
)
```

No roles or groups are automatically assigned unless an explicit later policy is introduced.

New users therefore receive no document authorization by default.

### Pre-provision-only policy

If JIT is disabled, an unknown verified external identity must fail with a local project error such as `LocalIdentityNotProvisioned`.

Do not silently create a user when policy says pre-provisioning is required.

---

## 11. HTTP Boundary

HTTP/FastAPI code should be thin.

Conceptual path:

```text
Authorization: Bearer <token>
       |
       v
extract token
       |
       v
TokenVerifier.verify(token)
       |
       v
IdentityResolver.resolve(identity)
       |
       v
CurrentUser / Principal dependency
```

FastAPI-specific `Depends`, HTTP exceptions, and status codes should remain at the API/boundary layer.

The contract and Identity module should not depend on FastAPI.

Recommended HTTP mapping:

```text
missing bearer token         -> 401
invalid/untrusted token      -> 401
unsupported issuer/audience  -> 401
valid external identity but locally disabled -> 403 (or project-wide chosen policy)
valid external identity but not provisioned when JIT disabled -> 403
```

The project should choose one consistent mapping and test it.

---

## 12. Security Requirements

Mandatory properties:

- never trust decoded claims before signature/issuer/time validation;
- fail closed;
- never log raw bearer tokens;
- never log refresh tokens;
- do not accept arbitrary issuers supplied by the token itself;
- use configured trusted issuer(s);
- validate intended audience/client policy;
- do not use email as the durable identity key;
- do not accept Keycloak roles/groups as document authorization unless a later ADR explicitly changes that decision;
- do not fall back to anonymous/local identity when verification fails;
- do not let provider-specific exceptions leak into business code.

---

## 13. Error Contract

Base error:

```python
class TokenVerificationError(Exception):
    pass
```

Optional project-specific subclasses:

```python
class TokenExpiredError(TokenVerificationError):
    pass


class TokenIssuerError(TokenVerificationError):
    pass


class TokenAudienceError(TokenVerificationError):
    pass


class TokenClaimsError(TokenVerificationError):
    pass
```

Do not over-model errors unless callers genuinely need distinct behavior. A single `TokenVerificationError` is acceptable for the first implementation, with structured internal logging for the exact reason.

---

## 14. Testing Contract

### TokenVerifier contract tests

Every implementation must satisfy the same behavior.

Test success:

- valid token -> correct issuer;
- valid token -> correct subject;
- optional fields map correctly;
- returned object is immutable.

Test failure:

- malformed token;
- invalid signature;
- expired token;
- wrong issuer;
- wrong audience;
- missing `sub`;
- missing `iss`;
- unsupported algorithm according to policy.

### Adapter tests

Mock/stub network metadata/JWKS where appropriate.

Test:

- key cache behavior;
- one refresh on unknown `kid`;
- failure after unresolved key;
- provider exceptions translated to project errors.

### Integration tests

Against a disposable/test Keycloak instance:

- obtain/prepare a real valid access token;
- verify it;
- resolve the local identity;
- assert local Principal behavior;
- assert invalid realm/issuer tokens are rejected.

---

## 15. Performance Requirements

Token verification should not make an external Keycloak HTTP request on every API request.

Expected normal path:

```text
request
  -> local JWT verification using cached signing material
  -> local identity lookup
```

Discovery/JWKS network requests belong on cache miss/refresh paths, not normal request paths.

Local identity resolution should use the active identifier index:

```text
(identifier_type, issuer, normalized_value)
WHERE valid_to IS NULL
```

---

## 16. Observability Requirements

Useful structured fields:

```text
request_id
auth_provider = keycloak
issuer
verification_outcome
verification_error_code
local_principal_id when resolved
provisioning_outcome
```

For sensitive external subjects, prefer logging the local Principal ID or a one-way/redacted representation where operationally sufficient.

Never include the token itself in logs or traces.

---

## 17. Dependency Rules

Allowed:

```text
contracts/authentication.py
    <- platform/auth/keycloak.py
    <- modules/identity application logic uses contract types
```

Composition:

```text
bootstrap
   creates KeycloakTokenVerifier
   wires it to API/application dependencies
```

Current composition:

```text
bootstrap/lifespan.py
    -> KeycloakTokenVerifier
    -> application.state.token_verifier
    -> get_authenticated_identity
```

Forbidden:

```text
modules/identity imports Keycloak SDK
modules/identity imports platform.auth.keycloak
contracts imports platform
```

---

## 18. Change Rules

Changes to this contract require explicit architectural review when they affect any of the following:

- stable external identity key;
- trusted issuers;
- whether Keycloak roles/groups become authorization inputs;
- provisioning policy;
- local Principal identity semantics;
- document authorization boundary;
- multi-provider identity support.

Provider-internal refactors that continue to satisfy this contract do not require downstream Identity changes.

---

## 19. v1 Definition of Done

The authentication boundary is implemented when:

- `AuthenticatedIdentity` exists;
- `TokenVerifier` Protocol exists;
- Keycloak implementation exists behind the Protocol;
- configured issuer/audience/signature/time claims are verified;
- JWKS is cached and refreshed safely;
- failures map to project-level authentication errors;
- raw token is not exposed beyond the auth boundary unnecessarily;
- verified identity resolves through `oidc_subject + issuer` to a local Principal;
- local disabled/retired identity is enforced;
- integration tests against Keycloak pass;
- application code outside the adapter contains no Keycloak-specific token-verification logic.

The remaining work for the complete identity vertical slice is local identity resolution
on protected business routes and integration tests against the disposable Keycloak realm.
