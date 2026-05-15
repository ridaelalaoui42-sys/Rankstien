"""
RankStein Pinterest Automation — Circuit Breaker
Prevents cascading failures by opening the circuit after threshold breaches.
"""

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from threading import RLock

from .config import DATA_DIR, get_config

logger = logging.getLogger("rankstein.circuit")

CIRCUIT_STATE_FILE = DATA_DIR / "circuit_state.json"


class CircuitState(Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing fast, rejecting calls
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Production circuit breaker for Pinterest automation.
    Tracks failures per-operation-type and opens circuit when threshold exceeded.
    """

    def __init__(self):
        self.config = get_config().circuit_breaker
        self._state_file = CIRCUIT_STATE_FILE
        self._lock = RLock()
        self._states: dict = {}
        self._failure_counts: dict = {}
        self._success_counts: dict = {}
        self._last_failure_time: dict = {}
        self._state_change_callbacks: list[Callable[[str, CircuitState], None]] = []
        self._last_disk_load: float = 0.0  # epoch; 0 forces immediate load
        self._disk_reload_interval: float = 30.0  # re-read file every 30 s
        self._last_save_time: float = 0.0
        self._dirty: bool = False
        self._load_state()

    def _load_state(self):
        if self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                self._states = data.get("states", {})
                self._failure_counts = data.get("failure_counts", {})
                self._success_counts = data.get("success_counts", {})
                self._last_failure_time = data.get("last_failure_time", {})
                self._last_disk_load = time.time()
                self._dirty = False
            except Exception as e:
                logger.warning(f"Failed to load circuit state: {e}")

    def _maybe_reload_from_disk(self):
        """Re-read the state file if the reload interval has elapsed.

        This means an external ``circuit_state.json`` reset (e.g. by the
        operator) propagates into the running process within 30 seconds
        without requiring a restart.
        """
        if time.time() - self._last_disk_load >= self._disk_reload_interval:
            logger.debug("Circuit breaker: reloading state from disk")
            self._load_state()

    def _save_state(self, force: bool = False):
        """Save state to disk with interval-based throttling."""
        if not self._dirty and not force:
            return

        now = time.time()
        if not force and (now - self._last_save_time < self.config.save_interval_seconds):
            return

        try:
            state = {
                "states": self._states,
                "failure_counts": self._failure_counts,
                "success_counts": self._success_counts,
                "last_failure_time": self._last_failure_time,
                "timestamp": datetime.now(UTC).timestamp(),
            }
            self._state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
            self._last_save_time = now
            self._dirty = False
            logger.debug("Circuit breaker: saved state to disk")
        except Exception as e:
            logger.warning(f"Failed to save circuit state: {e}")

    def flush(self):
        """Force save state to disk immediately."""
        with self._lock:
            self._save_state(force=True)

    def register_state_change_callback(self, callback: Callable[[str, CircuitState], None]):
        self._state_change_callbacks.append(callback)

    def _set_state(self, operation: str, state: CircuitState):
        old = self._states.get(operation)
        self._states[operation] = state.value
        if old != state.value:
            logger.warning(f"Circuit '{operation}': {old} -> {state.value}")
            for cb in self._state_change_callbacks:
                try:
                    cb(operation, state)
                except Exception as e:
                    logger.error(f"Circuit callback error: {e}")
            self._dirty = True
            self._save_state(force=True)  # Always force save on state transition

    def get_state(self, operation: str) -> CircuitState:
        with self._lock:
            self._maybe_reload_from_disk()  # honour external file resets
            val = self._states.get(operation, CircuitState.CLOSED.value)
            state = CircuitState(val)

            # Auto-recovery: OPEN -> HALF_OPEN after timeout
            if state == CircuitState.OPEN:
                last_fail = self._last_failure_time.get(operation, 0)
                if time.time() - last_fail >= self.config.recovery_timeout_seconds:
                    logger.info(f"Circuit '{operation}' timeout elapsed, entering HALF_OPEN")
                    self._set_state(operation, CircuitState.HALF_OPEN)
                    self._success_counts[operation] = 0
                    return CircuitState.HALF_OPEN
            return state

    def record_success(self, operation: str):
        with self._lock:
            self._failure_counts[operation] = 0
            state = self.get_state(operation)

            if state == CircuitState.HALF_OPEN:
                self._success_counts[operation] = self._success_counts.get(operation, 0) + 1
                if self._success_counts[operation] >= self.config.success_threshold_to_close:
                    logger.info(f"Circuit '{operation}' recovered, closing circuit")
                    self._set_state(operation, CircuitState.CLOSED)
                    self._success_counts[operation] = 0

            self._dirty = True
            self._save_state()

    def record_failure(self, operation: str, retryable: bool = True):
        with self._lock:
            self._failure_counts[operation] = self._failure_counts.get(operation, 0) + 1
            self._last_failure_time[operation] = time.time()

            state = self.get_state(operation)

            if state == CircuitState.HALF_OPEN:
                logger.warning(f"Circuit '{operation}' failed in HALF_OPEN, re-opening")
                self._set_state(operation, CircuitState.OPEN)
            elif state == CircuitState.CLOSED:
                if self._failure_counts[operation] >= self.config.failure_threshold:
                    logger.error(
                        f"Circuit '{operation}' opened after {self._failure_counts[operation]} failures"
                    )
                    self._set_state(operation, CircuitState.OPEN)

            self._dirty = True
            self._save_state()

    def can_execute(self, operation: str) -> bool:
        state = self.get_state(operation)
        if state == CircuitState.OPEN:
            return False
        if state == CircuitState.HALF_OPEN:
            # Allow limited calls in half-open
            calls = self._success_counts.get(operation, 0)
            return calls < self.config.half_open_max_calls
        return True

    def reset(self, operation: str | None = None):
        """Manually reset the circuit breaker state."""
        with self._lock:
            if operation:
                self._states[operation] = CircuitState.CLOSED.value
                self._failure_counts[operation] = 0
                self._success_counts[operation] = 0
                logger.info(f"Circuit '{operation}' manually reset to CLOSED")
            else:
                self._states = {}
                self._failure_counts = {}
                self._success_counts = {}
                self._last_failure_time = {}
                logger.info("All circuits manually reset to CLOSED")
            self._dirty = True
            self._save_state(force=True)

    def call(self, operation: str, func, *args, **kwargs):
        """Wrapper that checks circuit before executing."""
        if not self.can_execute(operation):
            raise CircuitBreakerOpenError(f"Circuit '{operation}' is OPEN")
        try:
            result = func(*args, **kwargs)
            self.record_success(operation)
            return result
        except Exception as e:
            retryable = not isinstance(e, (AuthenticationError, FatalAutomationError))
            self.record_failure(operation, retryable=retryable)
            raise


class CircuitBreakerOpenError(Exception):
    pass


class AuthenticationError(Exception):
    pass


class FatalAutomationError(Exception):
    pass


# Singleton
_circuit_breaker: CircuitBreaker | None = None


def get_circuit_breaker() -> CircuitBreaker:
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker


def reset_singleton() -> CircuitBreaker:
    """Destroy and recreate the singleton, forcing a fresh disk load.

    Call this after writing a reset ``circuit_state.json`` so the running
    process immediately picks up the new state.
    """
    global _circuit_breaker
    _circuit_breaker = None
    return get_circuit_breaker()
