import logging
import traceback
from functools import wraps

logger = logging.getLogger("tacklebox")


def fail_open(handler):
    """Decorator that ensures any unhandled exception returns {} with 200."""

    @wraps(handler)
    async def wrapper(*args, **kwargs):
        try:
            return await handler(*args, **kwargs)
        except Exception:
            logger.error(
                f"Handler {handler.__name__} failed, returning empty response:\n"
                f"{traceback.format_exc()}"
            )
            return {}

    return wrapper
