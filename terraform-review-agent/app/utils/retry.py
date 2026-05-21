import asyncio
import functools
from typing import TypeVar, Callable, Any
from app.utils.logger import get_logger

F = TypeVar("F", bound=Callable[..., Any])

logger = get_logger(__name__)


def async_retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            current_delay = delay

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    logger.warning(
                        "retry_attempt_failed",
                        func=func.__name__,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        error=str(e),
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff

            raise last_exception  # type: ignore

        return wrapper  # type: ignore

    return decorator
