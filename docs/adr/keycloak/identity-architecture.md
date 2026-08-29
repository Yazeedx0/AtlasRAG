# AtlasRAG Identity Architecture

**Status:** Project design document  
**Scope:** Identity, authentication boundary, local authorization identity, provisioning, lifecycle, role/group resolution, and security hand-off to ACL/retrieval  
**Target architecture:** Production-oriented modular monolith  
**Authentication provider:** Keycloak (OIDC/OAuth 2.0)  
**Authorization source of truth:** AtlasRAG

---

## 1. Purpose

AtlasRAG is an enterprise RAG system in which authentication and authorization must be treated as separate concerns.

Keycloak is responsible for proving who the caller is. AtlasRAG is responsible for deciding what that authenticated identity means inside the application and what the user is allowed to access.

The core split is:

```text
Keycloak
  = authentication provider
  = credentials, MFA, SSO, sessions, refresh-token lifecycle

AtlasRAG
  = local identity projection
  = Principal/User mapping
  = roles and groups
  = document-level authorization
  = effective-principal resolution
```

This separation is intentional. AtlasRAG must not make Keycloak's internal user identifier the permanent domain identity used by document ACLs, audit data, or other durable business records.

---

## 2. System Boundary

The request path is:

```text
Frontend
   |
   | login / OIDC flow
   v
Keycloak
   |
   | access token (JWT)
   v
AtlasRAG API
   |
   | 1. verify token
   | 2. convert verified claims into AuthenticatedIdentity
   | 3. resolve local User / Principal
   | 4. enforce local principal lifecycle
   | 5. compute effective principals
   v
Knowledge authorization / ACL
   |
   | authorized documents only
   v
Retrieval
   |
   v
LLM context
```

A restricted document must never be retrieved first and filtered later. Authorization is resolved before restricted content can enter semantic search results or LLM context.

---

## 3. Authentication vs. Identity vs. Authorization

### 3.1 Authentication

Authentication answers:

> Who is the caller?

Keycloak owns this concern.

AtlasRAG does not store user passwords and does not implement its own refresh-token/session state.

Keycloak owns, among other things:

- login flows;
- credential validation;
- password lifecycle;
- MFA;
- SSO;
- OIDC/OAuth token issuance;
- authentication sessions;
- refresh tokens;
- logout/session revocation;
- optional federation to LDAP/Active Directory or other identity stores.

AtlasRAG receives an access token and verifies that it can be trusted.

AtlasRAG is intentionally a stateless resource server in v1. The API does not expose or
persist its own login, OIDC callback, logout, refresh-token, or authentication-session
lifecycle. Keycloak owns those concerns, while the frontend or BFF is responsible for
obtaining and presenting the access token. The API validates that token on every request,
then performs local identity resolution and authorization.

The intended request flow is:

```text
Frontend / BFF
      | login, callback, token handling, logout
      v
Keycloak
      | access token
      v
AtlasRAG API
      | verify bearer token
      | resolve (issuer, subject) to local Principal
      | enforce AtlasRAG authorization
      v
Protected resource / retrieval
```

Therefore, the absence of session tables or authentication lifecycle endpoints in AtlasRAG
is a deliberate boundary decision, not a missing v1 feature. JWT access tokens remain
accepted until their normal expiry unless a separate revocation/introspection policy is
introduced for sensitive operations.

### 3.2 Identity

Identity answers:

> Which AtlasRAG user does this trusted external identity correspond to?

AtlasRAG owns this concern.

The external OIDC identity is mapped to a stable local Principal through `iam.user_identifiers`.

Conceptually:

```text
OIDC issuer + subject
        |
        v
iam.user_identifiers
        |
        v
iam.users
        |
        v
iam.principals
```

The Keycloak `sub` claim is not the AtlasRAG `principal.id`.

### 3.3 Authorization

Authorization answers:

> What may this AtlasRAG Principal access?

AtlasRAG owns this concern through:

- `iam.user_roles`;
- `iam.group_memberships`;
- local Principal lifecycle;
- later, `knowledge.document_acl`.

Keycloak roles/groups are not the v1 authorization source of truth for AtlasRAG document access.

---

## 4. Identity Persistence Model

With Keycloak adopted, the local identity persistence for v1 is:

```text
iam.principals
iam.users
iam.user_identifiers
iam.roles
iam.groups
iam.user_roles
iam.group_memberships
```

The following self-hosted-auth tables are intentionally not part of the AtlasRAG v1 identity model:

```text
iam.auth_sessions       -- removed / not created
iam.refresh_tokens      -- removed / not created
users.password_hash     -- removed
```

### 4.1 Principal

`Principal` is the durable authorization identity.

Supported principal types:

```text
user
role
group
```

Important invariants:

- `principal.id` is immutable;
- `principal.type` is immutable;
- a deleted principal cannot remain active;
- only active, non-deleted principals participate in authorization;
- every Principal must have exactly one matching specialization:
  - `user -> iam.users`
  - `role -> iam.roles`
  - `group -> iam.groups`

### 4.2 User

`iam.users` is a specialization of `Principal`.

Its primary key is also the foreign key to the Principal:

```text
users.principal_id
    = PK
    = FK -> principals.id
```

A User does not receive a second independent identity UUID.

### 4.3 UserIdentifier

`iam.user_identifiers` stores external/login identifiers with lifecycle history.

Supported examples include:

- email;
- employee number;
- OIDC subject;
- future enterprise-directory identifiers.

For Keycloak/OIDC, the canonical mapping is:

```text
identifier_type  = oidc_subject
issuer           = <OIDC iss claim>
normalized_value = <OIDC sub claim>
```

The identity key is `(issuer, subject)`, not `subject` alone.

This matters because different issuers can legally produce the same subject value.

### 4.4 Roles

Roles are local AtlasRAG authorization concepts.

v1 policy:

- roles are flat;
- roles are assigned directly to users;
- `role_key` is stable and never reused;
- assignments are temporal rather than physically deleted.

### 4.5 Groups

Groups are local AtlasRAG membership concepts.

v1 supports:

- user -> group membership;
- group -> group membership;
- nested groups;
- temporal membership history;
- no group cycles;
- no role as a group member.

`group_key` is stable and never reused.

---

## 5. Why the Local Principal Must Not Equal Keycloak `sub`

Using the external provider's identifier as the permanent business identity creates unnecessary coupling.

AtlasRAG instead keeps:

```text
external identity:
  issuer + subject

local identity:
  principal.id
```

Benefits:

1. Keycloak can be replaced without rewriting every foreign key in the application.
2. A user can gain additional identifiers over time.
3. Historical authorization remains meaningful even if an external identifier changes.
4. ACL, citations, audit, and future domain records depend on AtlasRAG's own stable identity.
5. Multiple identity providers can be supported later without changing the Principal model.

---

## 6. Authentication Boundary

Raw JWTs are untrusted input.

Application code must not treat decoded claims as authenticated merely because the token can be parsed.

The flow is:

```text
raw token
   |
   v
TokenVerifier
   |
   | validate
   | - cryptographic signature
   | - issuer
   | - intended audience/client
   | - expiration
   | - not-before where applicable
   | - required claims
   v
AuthenticatedIdentity
```

Only after successful verification do claims become trusted application facts.

The rest of AtlasRAG should work with `AuthenticatedIdentity`, not with raw JWT dictionaries.

---

## 7. AuthenticatedIdentity

`AuthenticatedIdentity` is an internal immutable value object representing trusted external identity facts.

Recommended contract:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    issuer: str
    subject: str
    email: str | None = None
    email_verified: bool | None = None
    username: str | None = None
    display_name: str | None = None
```

Required identity key:

```text
issuer + subject
```

Optional profile attributes are convenience data only. They must not replace the stable identity key.

Roles/groups are intentionally absent from this object in v1 because authentication facts and AtlasRAG authorization state are separate concerns.

---

## 8. Vertical-Slice Implementation Strategy

Identity is implemented as a complete capability before moving to Knowledge/RAG persistence.

The slice is:

```text
identity persistence
       +
authentication contract
       +
Keycloak adapter
       +
local identity resolution
       +
provisioning policy
       +
principal lifecycle
       +
role/group behavior
       +
effective-principal resolution
       +
tests
```

Only after this slice is stable should Knowledge/ACL/Retrieval begin to depend on it.

This prevents AtlasRAG from becoming a large collection of tables whose business behavior is implemented much later.

---

## 9. Local Identity Resolution

After the token is verified, AtlasRAG resolves the authenticated external identity to a local user.

Input:

```text
AuthenticatedIdentity
  issuer
  subject
```

Lookup:

```text
iam.user_identifiers
WHERE identifier_type = 'oidc_subject'
  AND issuer = :issuer
  AND normalized_value = :subject
  AND valid_to IS NULL
```

Then:

```text
UserIdentifier
   -> User
   -> Principal
```

The resulting Principal must satisfy:

```text
is_active = true
AND deleted_at IS NULL
```

A valid Keycloak account does not automatically imply valid AtlasRAG access.

This gives AtlasRAG a local application-level disable/retirement control independent of the IdP.

---

## 10. Provisioning Policy

A verified Keycloak user may not yet exist locally.

Two general policies are possible:

### Pre-provisioning

An administrator or synchronization process creates all AtlasRAG users before their first login.

### Just-in-time (JIT) provisioning

The first successful authenticated request creates the local identity projection.

Recommended v1 default: **JIT provisioning**, unless organizational policy requires explicit pre-provisioning.

The JIT transaction is atomic:

```text
BEGIN

create Principal(type=user)
create User(principal_id=<same id>)
create UserIdentifier(
    type=oidc_subject,
    issuer=<iss>,
    normalized_value=<sub>
)

COMMIT
```

Security property:

> A newly provisioned user receives zero roles, zero groups, and zero document grants by default.

Therefore authentication does not imply authorization.

Default authorization remains deny.

### Concurrency requirement

Two concurrent first requests for the same `(issuer, subject)` must not create two local users.

The active unique constraint on `user_identifiers` is the final database guard. Application code should treat a uniqueness race as a recoverable resolution race: re-query the existing identity after the conflicting transaction wins.

---

## 11. Principal Lifecycle

The identity application service must expose business operations rather than generic CRUD.

Examples:

```text
activate_principal(...)
deactivate_principal(...)
retire_principal(...)
```

### Deactivate

A deactivated principal remains historically present but no longer participates in authorization.

Conceptually:

```text
is_active = false
status_changed_at = now
```

### Retire

Retirement is stronger than temporary deactivation.

Conceptually:

```text
is_active = false
deleted_at = now
status_changed_at = now
```

If external identifiers are intentionally released, their `valid_to` is closed in the same business transaction according to identity-lifecycle policy.

---

## 12. Role Logic

Role assignment is a business operation, not generic row creation.

Recommended operations:

```text
assign_role(user_principal_id, role_principal_id, actor_principal_id, assigned_at)
revoke_role(user_principal_id, role_principal_id, actor_principal_id, revoked_at)
list_active_roles(user_principal_id)
```

Rules:

- target User must exist;
- target Role must exist;
- authorization resolution ignores inactive/deleted role Principals;
- only one active assignment for the same user-role pair;
- historical rows are retained;
- revocation closes the current assignment rather than deleting it.

Temporal example:

```text
Ahmad -> Engineering
2025 -------- 2026

Ahmad -> Engineering
2028 -------- current
```

Both records are valid history. Only the second is active now.

---

## 13. Group Logic

Recommended operations:

```text
add_group_member(group_id, member_id, member_type, actor_id, added_at)
remove_group_member(group_id, member_id, actor_id, removed_at)
list_direct_members(group_id)
list_direct_groups_for_member(member_id)
```

Rules:

- a Group may contain a User;
- a Group may contain another Group;
- a Group may not contain a Role;
- direct self-membership is invalid;
- the active membership graph must be acyclic;
- historical memberships are retained;
- only one active membership for the same `(group, member)` pair.

The graph may be a DAG; it is not constrained to a strict tree.

Example:

```text
Engineering Team -> All Technical Staff
Project Atlas    -> All Technical Staff
```

A group may therefore be reachable through more than one parent path, provided the active graph remains acyclic.

---

## 14. Effective Principals

The most important Identity output for future authorization is the set of Principals that currently represent the authenticated user.

For a user, effective principals include:

1. the user's own Principal;
2. every active Role assigned directly to the user;
3. every active Group directly containing the user;
4. every active ancestor Group reachable through nested group membership.

Example:

```text
User Ahmad        = U1
Engineering Role  = R1
Employee Role     = R2
Jordan Group      = G1
Engineering Group = G2
All Employees     = G3

U1 -> R1
U1 -> R2
U1 member of G1
U1 member of G2
G2 member of G3
```

Effective set:

```text
{ U1, R1, R2, G1, G2, G3 }
```

Only active, non-deleted Principals may appear in the result.

Only active temporal edges may participate:

```text
user_roles.revoked_at IS NULL

group_memberships.removed_at IS NULL
```

Recommended application-facing contract:

```python
async def resolve_effective_principal_ids(
    user_principal_id: UUID,
) -> frozenset[UUID]:
    ...
```

A richer result object may later be useful for debugging/audit, but downstream authorization should not need to know how the set was derived.

---

## 15. Security Hand-Off to Document ACL

Future Knowledge/Retrieval code should depend on the Identity module through effective principals, not by reimplementing role/group traversal.

Correct flow:

```text
Authenticated user
      |
      v
Identity module
      |
      v
Effective Principal IDs
      |
      v
Document ACL filter
      |
      v
Authorized candidate documents/chunks
      |
      v
Similarity / lexical retrieval
      |
      v
LLM context
```

Incorrect flow:

```text
retrieve all relevant chunks
      |
      v
filter unauthorized chunks later
```

The incorrect flow allows restricted content to enter retrieval/intermediate processing and creates an unnecessary disclosure risk.

AtlasRAG therefore treats authorization filtering as part of retrieval correctness, not as presentation-layer cleanup.

---

## 16. Package Architecture

Recommended structure:

```text
src/atlasrag/
├── contracts/
│   └── authentication.py
│
├── modules/
│   └── identity/
│       ├── models/
│       │   ├── principal.py
│       │   ├── user.py
│       │   ├── user_identifier.py
│       │   ├── role.py
│       │   ├── user_role.py
│       │   ├── group.py
│       │   └── group_membership.py
│       ├── services/
│       └── errors.py
│
├── platform/
│   └── auth/
│       └── keycloak.py
│
└── bootstrap/
    └── ... composition / wiring ...
```

Dependency direction:

```text
modules -> contracts
platform -> contracts
bootstrap -> modules + platform + contracts
```

Forbidden dependency:

```text
modules/identity -> platform/auth/keycloak
```

The Identity domain/application layer must not import Keycloak-specific implementation details.

---

## 17. Testing Strategy

Identity must be tested before downstream Knowledge/RAG code depends on it.

### Contract/unit tests

Test:

- `AuthenticatedIdentity` immutability;
- verifier success contract;
- verifier failure maps to project authentication error;
- required issuer/subject behavior.

### Identity resolution tests

Test:

- active OIDC identifier resolves to the correct User/Principal;
- unknown identity follows configured provisioning policy;
- inactive principal is rejected;
- deleted principal is rejected;
- expired/closed identifier is not treated as current;
- `(issuer, subject)` disambiguates identities correctly.

### JIT provisioning tests

Test:

- first login creates Principal + User + OIDC identifier atomically;
- the three records share the correct identity relation;
- new user gets no roles/groups by default;
- duplicate concurrent provisioning does not produce duplicate active OIDC identifiers.

### Role tests

Test:

- assign role;
- reject duplicate active assignment;
- revoke role;
- reassign a previously revoked role;
- historical records remain;
- inactive role is omitted from effective authorization.

### Group tests

Test:

- direct user membership;
- nested group membership;
- role cannot be a group member;
- self-membership rejected;
- cycle rejected;
- removed memberships are ignored;
- multiple paths to the same ancestor deduplicate correctly.

### Effective-principal tests

Test:

- direct user principal included;
- active roles included;
- direct groups included;
- nested ancestor groups included;
- duplicate paths deduplicated;
- revoked/removed relationships excluded;
- inactive/deleted principals excluded.

---

## 18. Observability and Audit Requirements

Authentication and authorization should be observable without logging credentials or raw tokens.

Safe diagnostic fields may include:

```text
request_id
issuer
subject hash or local principal_id
resolution outcome
provisioning outcome
authorization principal count
error code
```

Avoid logging:

- raw access tokens;
- refresh tokens;
- authorization headers;
- passwords;
- unneeded PII.

Later audit events may record administrative identity changes such as:

```text
identity.principal.deactivated
identity.principal.retired
identity.role.assigned
identity.role.revoked
identity.group.member_added
identity.group.member_removed
```

Authentication session audit remains primarily a Keycloak responsibility, while AtlasRAG may record application-level authentication success/failure outcomes when useful.

---

## 19. Failure Model

Identity/authentication errors should be normalized into project-level errors.

Recommended categories:

```text
InvalidAuthenticationToken
UnsupportedAuthenticationIssuer
AuthenticationIdentityMissing
LocalIdentityDisabled
LocalIdentityNotProvisioned
IdentityProvisioningConflict
RoleAssignmentConflict
GroupMembershipConflict
GroupCycleDetected
```

Keycloak SDK/library exceptions must not leak through module boundaries.

---

## 20. v1 Non-Goals

The following are intentionally outside the v1 Identity scope unless explicitly added later:

- storing local passwords;
- implementing login, OIDC callback, logout, or authentication sessions inside AtlasRAG;
- implementing refresh-token rotation inside AtlasRAG;
- persisting Keycloak sessions in AtlasRAG;
- treating Keycloak roles/groups as the document-ACL source of truth;
- synchronizing the entire Keycloak realm into AtlasRAG;
- organization/tenant model beyond the current Principal design;
- deny ACL rules;
- role hierarchy;
- arbitrary policy language/ABAC engine.

---

## 21. Definition of Done for the Identity Vertical Slice

Identity is complete enough for Knowledge/ACL work when all of the following are true:

- Keycloak is the authentication provider;
- `TokenVerifier` contract exists;
- Keycloak adapter verifies configured issuer/audience/signature/time claims;
- verified claims are mapped into `AuthenticatedIdentity`;
- local `(issuer, subject)` resolution works;
- provisioning policy is implemented and tested;
- disabled/retired local Principals are rejected;
- role assignment/revocation works historically;
- group membership/removal works historically;
- group-cycle prevention is enforced;
- effective-principal resolution is correct and tested;
- Identity code does not depend directly on Keycloak implementation details;
- no local password/session/refresh-token persistence remains;
- database migrations for the final Identity schema pass upgrade/downgrade tests.

Once this DoD is met, Knowledge/Document ACL can safely depend on Identity.
