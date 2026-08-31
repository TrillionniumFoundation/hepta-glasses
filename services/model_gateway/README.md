# Development model gateway

This service proves that the mobile application calls a Hepta-owned gateway rather than embedding
provider endpoints or permanent provider credentials. The included provider is deterministic and
is **not** a production AI service.

Run locally:

```bash
HEPTA_GATEWAY_DEV_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  python3 services/model_gateway/app.py
```

Configure a development Flutter build with a loopback URL and the matching short-lived development
token. Product builds reject a compiled development token. Production identity, token minting,
provider routing, abuse controls, retention policy, and revoke remain external release blockers.
