# AtlasRAG API Reference

This document describes the HTTP API currently exposed by AtlasRAG.

## Conventions

The local development base URL is `http://localhost:8000`. All application endpoints use
the `/api/v1` prefix; health probes are intentionally unversioned.

Protected endpoints require a Keycloak access token:

```http
Authorization: Bearer <access_token>
```

UUID values are RFC 4122 strings. Timestamps are ISO 8601 datetimes with a timezone offset.
The interactive OpenAPI reference is available at `/docs`; the raw OpenAPI document is at
`/openapi.json`.

## Authorization capabilities

| Capability | Allows |
| --- | --- |
| `iam.principals.manage` | Activate, deactivate, and retire principals. |
| `iam.roles.manage` | List, assign, and revoke user roles. |
| `iam.groups.manage` | List, add, and remove group members. |
| `iam.permissions.manage` | List capability definitions and manage principal capability grants. |
| `knowledge.documents.manage` | Create, update, and soft-delete documents. |
| `knowledge.document_acl.manage` | List, create, and revoke document ACL grants. |

Management capabilities do not grant document content access. Document access remains controlled
by active document ACL grants.

## Endpoint summary

| Area | Method | Path | Required capability |
| --- | --- | --- | --- |
| Health | `GET` | `/health` | None |
| Health | `GET` | `/health/ready` | None |
| Authentication | `GET` | `/api/v1/auth/me` | Authenticated identity |
| Principals | `PATCH` | `/api/v1/iam/principals/{principal_id}/activate` | `iam.principals.manage` |
| Principals | `PATCH` | `/api/v1/iam/principals/{principal_id}/deactivate` | `iam.principals.manage` |
| Principals | `PATCH` | `/api/v1/iam/principals/{principal_id}/retire` | `iam.principals.manage` |
| Roles | `GET` | `/api/v1/iam/users/{user_id}/roles` | `iam.roles.manage` |
| Roles | `POST` | `/api/v1/iam/users/{user_id}/roles` | `iam.roles.manage` |
| Roles | `DELETE` | `/api/v1/iam/users/{user_id}/roles/{role_id}` | `iam.roles.manage` |
| Groups | `GET` | `/api/v1/iam/groups/{group_id}/members` | `iam.groups.manage` |
| Groups | `POST` | `/api/v1/iam/groups/{group_id}/members` | `iam.groups.manage` |
| Groups | `DELETE` | `/api/v1/iam/groups/{group_id}/members/{member_id}` | `iam.groups.manage` |
| Permissions | `GET` | `/api/v1/iam/permissions` | `iam.permissions.manage` |
| Permissions | `GET` | `/api/v1/iam/principals/{principal_id}/permissions` | `iam.permissions.manage` |
| Permissions | `POST` | `/api/v1/iam/principals/{principal_id}/permissions/{permission_key}` | `iam.permissions.manage` |
| Permissions | `DELETE` | `/api/v1/iam/principals/{principal_id}/permissions/{permission_key}` | `iam.permissions.manage` |
| Documents | `POST` | `/api/v1/documents` | `knowledge.documents.manage` |
| Documents | `PATCH` | `/api/v1/documents/{document_id}` | `knowledge.documents.manage` |
| Documents | `DELETE` | `/api/v1/documents/{document_id}` | `knowledge.documents.manage` |
| Document artifacts | `POST` | `/api/v1/documents/{document_id}/versions/{version_id}/artifacts` | `knowledge.documents.manage` |
| Document ACL | `GET` | `/api/v1/documents/{document_id}/acl` | `knowledge.document_acl.manage` |
| Document ACL | `POST` | `/api/v1/documents/{document_id}/acl` | `knowledge.document_acl.manage` |
| Document ACL | `DELETE` | `/api/v1/documents/{document_id}/acl/{grant_id}` | `knowledge.document_acl.manage` |

## Health

### `GET /health`

Returns `200 OK` when the API process is live.

```json
{
  "status": "ok",
  "service": "atlasrag",
  "version": "0.1.0"
}
```

### `GET /health/ready`

Returns `200 OK` when readiness checks pass, or `503 Service Unavailable` when a check fails.

```json
{
  "status": "ready",
  "checks": {}
}
```

## Authentication

### `GET /api/v1/auth/me`

Verifies the bearer token and resolves it to an active local AtlasRAG principal.

Returns `200 OK`:

```json
{
  "principal_id": "03ad1d95-73ec-4f65-a55d-a28446a49f4a",
  "issuer": "http://localhost:8080/realms/atlasrag",
  "subject": "ca6d49d5-3f4e-48d7-8a48-cd9bf9759d5e",
  "email": "atlas-admin@example.com",
  "email_verified": true,
  "username": "atlas-admin",
  "display_name": "Atlas Admin"
}
```

## IAM

### Principal lifecycle

The following endpoints accept no request body and return `204 No Content` on success:

| Method | Path | Effect |
| --- | --- | --- |
| `PATCH` | `/api/v1/iam/principals/{principal_id}/activate` | Makes an inactive principal active. |
| `PATCH` | `/api/v1/iam/principals/{principal_id}/deactivate` | Makes an active principal inactive. |
| `PATCH` | `/api/v1/iam/principals/{principal_id}/retire` | Permanently retires a principal. |

All require `iam.principals.manage`.

### User roles

#### `GET /api/v1/iam/users/{user_id}/roles`

Requires `iam.roles.manage`. Returns `200 OK` and active role assignments:

```json
[
  {
    "role_id": "ad887db0-94f5-4b83-9e64-0ce86d83b596",
    "role_key": "knowledge-manager",
    "name": "Knowledge Manager",
    "description": "Manages knowledge documents.",
    "assigned_at": "2026-08-30T12:00:00Z",
    "assigned_by_principal_id": "03ad1d95-73ec-4f65-a55d-a28446a49f4a"
  }
]
```

#### `POST /api/v1/iam/users/{user_id}/roles`

Requires `iam.roles.manage`. Assigns a role and returns `204 No Content`.

```json
{
  "role_id": "ad887db0-94f5-4b83-9e64-0ce86d83b596"
}
```

#### `DELETE /api/v1/iam/users/{user_id}/roles/{role_id}`

Requires `iam.roles.manage`. Revokes the active assignment and returns `204 No Content`.

### Group membership

#### `GET /api/v1/iam/groups/{group_id}/members`

Requires `iam.groups.manage`. Returns `200 OK` and direct active members:

```json
[
  {
    "membership_id": "28154f35-66b4-4fd2-b367-bc7b8e067e10",
    "member_id": "03ad1d95-73ec-4f65-a55d-a28446a49f4a",
    "member_type": "user",
    "added_at": "2026-08-30T12:00:00Z",
    "added_by_principal_id": "03ad1d95-73ec-4f65-a55d-a28446a49f4a"
  }
]
```

#### `POST /api/v1/iam/groups/{group_id}/members`

Requires `iam.groups.manage`. Adds a direct user or group member and returns `204 No Content`.

```json
{
  "member_id": "03ad1d95-73ec-4f65-a55d-a28446a49f4a"
}
```

A group cannot contain itself, and nested groups cannot introduce a membership cycle.

#### `DELETE /api/v1/iam/groups/{group_id}/members/{member_id}`

Requires `iam.groups.manage`. Removes the active membership and returns `204 No Content`.

### Capability permissions

#### `GET /api/v1/iam/permissions`

Requires `iam.permissions.manage`. Returns `200 OK` and registered capability definitions:

```json
[
  {
    "permission_key": "knowledge.documents.manage",
    "description": "Manage knowledge documents."
  }
]
```

#### `GET /api/v1/iam/principals/{principal_id}/permissions`

Requires `iam.permissions.manage`. Returns `200 OK` and active direct capability grants:

```json
[
  {
    "permission_key": "knowledge.documents.manage",
    "description": "Manage knowledge documents.",
    "granted_at": "2026-08-30T12:00:00Z",
    "granted_by_principal_id": "03ad1d95-73ec-4f65-a55d-a28446a49f4a"
  }
]
```

#### `POST /api/v1/iam/principals/{principal_id}/permissions/{permission_key}`

Requires `iam.permissions.manage`. Grants a registered capability and returns `204 No Content`.
`permission_key` must be one of the values in the authorization capabilities table.

#### `DELETE /api/v1/iam/principals/{principal_id}/permissions/{permission_key}`

Requires `iam.permissions.manage`. Revokes the active direct capability grant and returns
`204 No Content`.

## Documents

### Document representation

```json
{
  "id": "62a8c6bf-fc40-45b3-8eb7-5312deed5f23",
  "created_by_principal_id": "03ad1d95-73ec-4f65-a55d-a28446a49f4a",
  "canonical_key": "remote-work-policy",
  "title": "Remote Work Policy",
  "description": "Company remote-work guidelines.",
  "document_type": "policy",
  "department": "People",
  "default_language_code": "en",
  "metadata": {
    "version": "1.0"
  },
  "created_at": "2026-08-30T12:00:00Z",
  "updated_at": "2026-08-30T12:00:00Z"
}
```

### `POST /api/v1/documents`

Requires `knowledge.documents.manage`. Creates a logical document and returns `201 Created`.

```json
{
  "canonical_key": "remote-work-policy",
  "title": "Remote Work Policy",
  "description": "Company remote-work guidelines.",
  "document_type": "policy",
  "department": "People",
  "default_language_code": "en",
  "metadata": {
    "version": "1.0"
  }
}
```

`canonical_key` and `title` are required. `canonical_key` must be unique. The API derives the
document ID, creator, and timestamps. Creating a document does not create a document ACL grant.

### `PATCH /api/v1/documents/{document_id}`

Requires `knowledge.documents.manage`. Updates a document and returns `200 OK` with the document
representation. At least one field is required.

```json
{
  "title": "Remote Work Policy v2",
  "description": null,
  "metadata": {
    "version": "2.0"
  }
}
```

`canonical_key` is immutable. Omitted fields remain unchanged. Supplying `metadata` replaces the
complete metadata object. `title` and `metadata` cannot be `null`; the other mutable fields may
be set to `null`.

### `DELETE /api/v1/documents/{document_id}`

Requires `knowledge.documents.manage`. Soft-deletes a document and returns `204 No Content`.
The document and its history remain stored, but the document is no longer active.

## Document artifacts

### `POST /api/v1/documents/{document_id}/versions/{version_id}/artifacts`

Requires `knowledge.documents.manage`. Uploads an artifact to a draft document version and returns
`201 Created`. The request uses `multipart/form-data`:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact_key` | string | Yes | Unique key within the document version. |
| `language_code` | string | Yes | Accepted artifact language code (`ar` or `en` by default). |
| `file` | file | Yes | PDF, plain text, Markdown, HTML, or DOCX file. |
| `source_uri` | string | No | Optional source URI metadata. |
| `source_updated_at` | datetime | No | Optional timezone-aware source update timestamp. |

The server generates the artifact ID and storage key, calculates the SHA-256 hash, and records the
file size. The default maximum file size is `50 MiB` (`ATLAS_MAX_FILE_SIZE_BYTES`).

Example response:

```json
{
  "artifact_id": "1a91e5b8-2a9a-40fc-94f3-aec8e06b7f6a",
  "document_version_id": "7a7b55e7-ec92-4c3d-83d7-4bd5d85f7a76",
  "artifact_key": "primary-source",
  "language_code": "en",
  "mime_type": "application/pdf",
  "file_hash": "ee87...",
  "file_size_bytes": 1024
}
```

## Document ACL

Document ACL permissions are `read` and `manage`. An ACL grant is temporal and allow-only.

### ACL grant representation

```json
{
  "grant_id": "1a91e5b8-2a9a-40fc-94f3-aec8e06b7f6a",
  "principal_id": "03ad1d95-73ec-4f65-a55d-a28446a49f4a",
  "permission": "read",
  "granted_at": "2026-08-30T12:00:00Z",
  "granted_by_principal_id": "03ad1d95-73ec-4f65-a55d-a28446a49f4a",
  "expires_at": null,
  "revoked_at": null,
  "revoked_by_principal_id": null
}
```

### `GET /api/v1/documents/{document_id}/acl`

Requires `knowledge.document_acl.manage`. Returns `200 OK` and currently effective grants only:

```text
granted_at <= now
AND revoked_at IS NULL
AND (expires_at IS NULL OR expires_at > now)
```

Use `?include_history=true` to return active, expired, and revoked grants, including their
temporal fields.

### `POST /api/v1/documents/{document_id}/acl`

Requires `knowledge.document_acl.manage`. Creates an ACL grant and returns `201 Created`.

```json
{
  "principal_id": "03ad1d95-73ec-4f65-a55d-a28446a49f4a",
  "permission": "read",
  "expires_at": "2027-01-01T00:00:00Z"
}
```

`expires_at` is optional but, when supplied, must contain a timezone and be later than the grant
time. The API derives the grant ID and audit fields. A duplicate unrevoked
`(document_id, principal_id, permission)` grant returns a conflict.

### `DELETE /api/v1/documents/{document_id}/acl/{grant_id}`

Requires `knowledge.document_acl.manage`. Revokes an active grant and returns `204 No Content`.
The grant is retained as ACL history; it is not physically deleted.

## Errors

Error responses use a JSON `detail` field:

```json
{
  "detail": "human-readable error message"
}
```

| Status | Meaning |
| --- | --- |
| `401 Unauthorized` | The bearer token is missing, malformed, expired, or invalid. |
| `403 Forbidden` | The caller lacks the required capability, or the token cannot resolve to usable local access. |
| `404 Not Found` | A requested document, ACL grant, principal, role assignment, membership, or permission does not exist. |
| `409 Conflict` | An operation violates an active-state or integrity rule, such as a duplicate grant, duplicate membership, group cycle, or protected superadmin operation. |
| `413 Content Too Large` | An uploaded artifact exceeds `ATLAS_MAX_FILE_SIZE_BYTES`. |
| `422 Unprocessable Content` | Request validation failed, or an ACL expiration is not later than its grant time. |
| `503 Service Unavailable` | A readiness check failed. |
