"""Auth headers for FastAPI's internal calls to the Next.js sidecar.

When PRESENTON_API_TOKEN is set, the Next.js middleware requires a Bearer
token on /api/* — FastAPI must send its own token on internal calls or
those calls 401 (which surfaces to users as cryptic "Template not found"
or export failures). No-op when the token is unset (local-dev mode)."""

import os


def internal_headers() -> dict[str, str]:
    token = os.environ.get("PRESENTON_API_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}
