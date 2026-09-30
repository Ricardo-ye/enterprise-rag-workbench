from collections import defaultdict, deque
from hmac import compare_digest
from threading import Lock
from time import monotonic


class FixedWindowRateLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        self.limit = requests_per_minute
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, identity: str) -> tuple[bool, int]:
        if self.limit == 0:
            return True, 0
        now = monotonic()
        cutoff = now - 60
        with self._lock:
            timestamps = self._requests[identity]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self.limit:
                retry_after = max(int(60 - (now - timestamps[0])) + 1, 1)
                return False, retry_after
            timestamps.append(now)
        return True, 0


def valid_api_key(expected: str | None, supplied: str | None) -> bool:
    if expected is None:
        return True
    if supplied is None:
        return False
    return compare_digest(expected.encode(), supplied.encode())
