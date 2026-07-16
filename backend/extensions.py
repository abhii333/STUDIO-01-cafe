"""Shared Flask extension instances.

These are created unbound and wired to the app in ``app.py`` via ``init_app``,
which keeps the blueprints free of any import dependency on the app module.
"""
from flask_jwt_extended import JWTManager

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except Exception:  # pragma: no cover - app still runs without the package
    Limiter = None
    get_remote_address = None

jwt = JWTManager()

if Limiter is not None:
    # In-memory storage (free-tier friendly, no Redis). Only decorated routes
    # are limited; enable/disable via the app's RATELIMIT_ENABLED config.
    limiter = Limiter(key_func=get_remote_address, default_limits=["120 per minute"], storage_uri='memory://')
else:
    class _NoopLimiter:
        """Fallback so @limiter.limit(...) is harmless if the package is absent."""
        def limit(self, *a, **k):
            def deco(fn):
                return fn
            return deco

        def init_app(self, app):
            pass

    limiter = _NoopLimiter()
