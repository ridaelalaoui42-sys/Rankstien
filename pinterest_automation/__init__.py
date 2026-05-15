"""
RankStein Pinterest Automation — Production-Grade Self-Healing Automation Engine

Unified package providing:
- pinterest_driver: High-level Playwright abstraction with self-healing
- supervisor: 24/7 autonomous operation with queue processing
- health_monitor: Persistent health tracking and recovery
- circuit_breaker: Failure isolation and automatic recovery
- session_pool: Browser session rotation and lifecycle management
- job_queue: Durable queue with retry and dead-letter handling
- rate_limiter: Intelligent rate limiting with anti-detection jitter
- self_healing: DOM analysis + LLM-powered selector recovery with caching
"""

from .circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, get_circuit_breaker
from .config import AutomationConfig, get_config
from .health_monitor import HealthMonitor, get_health_monitor
from .job_queue import Job, JobQueue, JobStatus, get_job_queue
from .pinterest_driver import PinterestDriver
from .rate_limiter import RateLimiter, get_rate_limiter
from .self_healing import fallback_heal, gemini_heal_selector, get_healing_cache, robust_fill
from .session_pool import SessionPool, get_session_pool
from .campaign import create_pinterest_campaign, enqueue_folder
from .supervisor import AutonomousSupervisor

__all__ = [
    "AutomationConfig",
    "AutonomousSupervisor",
    "create_pinterest_campaign",
    "enqueue_folder",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "HealthMonitor",
    "Job",
    "JobQueue",
    "JobStatus",
    "PinterestDriver",
    "RateLimiter",
    "SessionPool",
    "fallback_heal",
    "gemini_heal_selector",
    "get_circuit_breaker",
    "get_config",
    "get_healing_cache",
    "get_health_monitor",
    "get_job_queue",
    "get_rate_limiter",
    "get_session_pool",
    "robust_fill",
]
