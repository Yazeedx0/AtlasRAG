# Auth - Keycloak 


```bash 
                     ┌────────────────────┐
                     │      Keycloak      │
                     │                    │
Login / Password ───►│ OIDC               │
MFA              ───►│ Sessions           │
Refresh tokens   ───►│ Token rotation     │
LDAP / AD        ───►│ Federation         │
                     └─────────┬──────────┘
                               │
                               │ JWT / OIDC claims
                               ▼
                     ┌────────────────────┐
                     │      AtlasRAG      │
                     │                    │
                     │ Principal          │
                     │ User identity map  │
                     │ Roles / Groups     │
                     │ Document ACL       │
                     │ Authorization      │
                     └────────────────────┘
```
