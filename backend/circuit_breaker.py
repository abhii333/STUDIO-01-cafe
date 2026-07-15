"""Lightweight in-process circuit breaker for external dependencies.

Prevents a slow/failing dependency (Razorpay, Cloudinary, SMTP) from
cascading into thread exhaustion on our single-worker gunicorn.

States:
  CLOSED  — normal; calls go through.
  OPEN    — dependency is down; calls fast-fail immediately without waiting.
  HALF    — after the recovery window, one probe call is allowed through;
            if it succeeds, move back to CLOSED; if it fails, stay OPEN.

Thread-safe (uses a threading lock) since gunicorn gthread shares threads.
No external dependencies (free-tier safe).
"""
import time
import threading
from functools import wraps


class CircuitBreaker:
    CLOSED = 'closed'
    OPEN = 'open'
    HALF_OPEN = 'half_open'

    def __init__(self, name, failure_threshold=3, recovery_timeout=30, call_timeout=10):
        """
        Args:
            name: human label for logging
            failure_threshold: consecutive failures before tripping open
            recovery_timeout: seconds to wait before allowing a probe call
            call_timeout: max seconds a wrapped call is allowed to take (not enforced
                          here — callers should set their own socket/request timeout to
                          this value; the breaker tracks whether they raised on timeout)
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.call_timeout = call_timeout
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0
        self._lock = threading.Lock()

    @property
    def state(self):
        with self._lock:
            if self._state == self.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = self.HALF_OPEN
            return self._state

    def record_success(self):
        with self._lock:
            self._failure_count = 0
            self._state = self.CLOSED

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._state = self.OPEN

    def call(self, fn, *args, fallback=None, **kwargs):
        """Execute fn if the circuit allows it; otherwise return fallback.

        Args:
            fn: callable to invoke
            fallback: value to return when the circuit is open (fast-fail)
        Returns:
            fn's return value, or fallback if circuit is open
        Raises:
            CircuitOpenError if circuit is open and no fallback is provided
        """
        current = self.state
        if current == self.OPEN:
            if fallback is not None:
                return fallback() if callable(fallback) else fallback
            raise CircuitOpenError(f'{self.name} circuit is open — dependency unavailable')
        try:
            result = fn(*args, **kwargs)
            self.record_success()
            return result
        except Exception as exc:
            self.record_failure()
            raise

    def protect(self, fallback=None):
        """Decorator form: @breaker.protect(fallback=lambda: default_value)"""
        def decorator(fn):
            @wraps(fn)
            def wrapper(*args, **kwargs):
                return self.call(fn, *args, fallback=fallback, **kwargs)
            wrapper._breaker = self
            return wrapper
        return decorator


class CircuitOpenError(Exception):
    """Raised when a call is attempted on an open circuit with no fallback."""
    pass


# Pre-configured breakers for our external dependencies.
# Tuned for a cafe with a single free-tier worker:
#   - Trip after 3 consecutive failures
#   - Stay open 30s before probing (avoids hammering a down service)
#   - Callers should set their own socket timeout to call_timeout seconds

razorpay_breaker = CircuitBreaker('razorpay', failure_threshold=3, recovery_timeout=30, call_timeout=10)
cloudinary_breaker = CircuitBreaker('cloudinary', failure_threshold=3, recovery_timeout=60, call_timeout=15)
smtp_breaker = CircuitBreaker('smtp', failure_threshold=2, recovery_timeout=60, call_timeout=10)
