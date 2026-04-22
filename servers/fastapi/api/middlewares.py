import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from utils.get_env import get_can_change_keys_env
from utils.user_config import update_env_with_user_config


class UserConfigEnvUpdateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if get_can_change_keys_env() != "false":
            update_env_with_user_config()
        return await call_next(request)


class BearerTokenAuthMiddleware(BaseHTTPMiddleware):
    """Require `Authorization: Bearer <PRESENTON_API_TOKEN>` on API routes.

    No-op if PRESENTON_API_TOKEN is unset (preserves local-dev ergonomics).
    Skips OpenAPI docs and CORS preflight."""

    SKIP_PREFIXES = ("/docs", "/openapi.json", "/redoc")

    async def dispatch(self, request: Request, call_next):
        token = os.environ.get("PRESENTON_API_TOKEN")
        if not token:
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)
        if any(request.url.path.startswith(p) for p in self.SKIP_PREFIXES):
            return await call_next(request)

        header = request.headers.get("authorization", "")
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "bearer" or value != token:
            return JSONResponse(
                {"detail": "Unauthorized"}, status_code=401
            )
        return await call_next(request)
