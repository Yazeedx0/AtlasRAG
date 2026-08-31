# AtlasRAG Bruno collection

This collection covers all 30 routes registered under `apps/api/routes` and includes one
development-only Keycloak request for obtaining a Bearer token.

## Setup

1. Open this directory as a collection in Bruno.
2. Select the `Local` environment.
3. Set the secret `seedUserPassword` environment variable to the password used by
   `scripts/seed_dev_data.py`.
4. Run `00 Authentication/Get Development Token`.
5. Run `00 Authentication/Get Current User` to verify authentication and capture
   `currentPrincipalId`.

The token request stores `accessToken` in the selected environment for the current Bruno
session. Alternatively, paste a token into the secret `accessToken` variable.

## Variables

The document workflow captures `documentId`, `versionId`, `artifactId`, and `grantId` from
successful create responses. Change `canonicalKey` before repeating the create request because
the API requires it to be unique.

The API does not expose list/create routes for principals, roles, or groups. Set these variables
to existing database IDs before using the corresponding IAM requests:

- `targetPrincipalId`
- `userId`
- `roleId`
- `groupId`
- `memberId`

`permissionKey` must be one of the six values returned by `List Permission Definitions`.
`aclPermission` must be `read` or `manage`. All timestamps must include a timezone offset.

## Execution safety

Do not run the entire collection indiscriminately. It contains state-changing requests, including
principal deactivation and irreversible principal retirement. The Knowledge folders are ordered
as a draft-to-cleanup workflow, and the final cleanup request soft-deletes the created document.

Optional `at`, `source_uri`, and `source_updated_at` fields are disabled by default in their
requests. Enable them in Bruno when needed.
