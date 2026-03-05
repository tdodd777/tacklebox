import logging
import traceback
from functools import wraps

logger = logging.getLogger("tacklebox")

# Counter for monitoring swallowed exceptions via /health endpoint.
fail_open_error_count: int = 0


def fail_open(handler):
    """Decorator that ensures any unhandled exception returns {} with 200.

    Security tradeoff: This silently swallows ALL exceptions (including
    potential auth errors, constraint violations, etc.) to ensure hooks
    never block Claude Code. The error count is exposed via /health so
    monitoring systems can alert on spikes.
    """

    @wraps(handler)
    async def wrapper(*args, **kwargs):
        global fail_open_error_count
        try:
            return await handler(*args, **kwargs)
        except Exception:
            fail_open_error_count += 1
            logger.error(
                f"Handler {handler.__name__} failed, returning empty response:\n"
                f"{traceback.format_exc()}"
            )
            return {}

    return wrapper
