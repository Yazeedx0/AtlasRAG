# AtlasRAG Data Model — Conceptual Overview

Simplified, conceptual views of the schema. For the full entity-relationship
diagram with columns and types, see [schema-erd.png](schema-erd.png).

## Layers

The schema is organized into four conceptual layers, each building on the one
above it.

```mermaid
flowchart TB
    subgraph Identity["Identity"]
        direction LR
        principals["principals"]
        users["users"]
        roles["roles"]
        groups["groups"]
        user_roles["user_roles"]
        group_memberships["group_memberships"]
    end

    subgraph Authorization["Authorization"]
        document_acl["document_acl"]
    end

    subgraph Knowledge["Knowledge"]
        direction LR
        documents["documents"] --> document_versions["document_versions"] --> chunks["chunks"]
    end

    subgraph Derived["Derived / Retrieval Data"]
        direction LR
        ingestion_runs["ingestion_runs"] --> ingestion_items["ingestion_items"]
        embedding_models["embedding_models"] --> chunk_embeddings["chunk_embeddings"]
    end

    Identity --> Authorization --> Knowledge --> Derived
```

## Principal Hierarchy

`principals` is the shared identity type behind users, roles, and groups —
every grant of access ultimately points back to a principal.

```mermaid
flowchart TB
    principals --> users
    principals --> roles
    principals --> groups
    users -. user_roles .-> roles
    groups -. group_memberships .-> groups
```

## Knowledge Chain

Each document flows through versioning, ingestion, chunking, and embedding
in a strict 1:N pipeline.

```mermaid
flowchart LR
    documents --> document_versions --> ingestion_items --> chunks --> chunk_embeddings --> embedding_models
```

## Access Resolution

How a user's effective permission on a document is resolved: directly, via
a role, or via group membership — always mediated by `document_acl`.

```mermaid
flowchart LR
    User -->|direct| Principal["Principal"]
    User -->|user_roles| RolePrincipal["Role Principal"]
    User -->|group membership| GroupPrincipal["Group Principal"]
    Principal --> document_acl["document_acl"]
    RolePrincipal --> document_acl
    GroupPrincipal --> document_acl
    document_acl --> document["document"]
```
```bash 
                        principals
                    /       |       \
                   /        |        \
                users     roles     groups
                  │          ▲          ▲
                  │          │          │
                  └──── user_roles      │
                                        │
                                group_memberships
                                 ▲             │
                                 └──── group ──┘
```