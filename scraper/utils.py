"""
RealityCheck: Shared Utility Functions
======================================

CS Concepts Demonstrated:
    - Environment Variable Management:
        The 12-Factor App methodology states that configuration should
        live in environment variables, not in code. This separates
        configuration from logic, allowing the same code to run in
        development, staging, and production without changes.

    - Structured Logging:
        A logging system that attaches metadata (timestamp, severity,
        module name) to every message. This is critical for debugging
        in production, because print() statements have no context
        and cannot be filtered by severity.

    - Async/Await (Cooperative Multitasking):
        Unlike threads (preemptive multitasking), async functions
        voluntarily yield control with 'await'. This is ideal for
        I/O-bound tasks (network calls, file reads) because there's
        no locking overhead. The event loop runs everything in a
        single thread, switching between tasks at 'await' points.

    - Random Sampling for Anti-Detection:
        Rotating User-Agent strings spoofs different browser/OS
        combinations. Combined with random delays, this mimics human
        browsing patterns and reduces the likelihood of being blocked.

Architecture Role:
    This module is the lowest-level dependency in the project.
    Every other module (scraper, parser, db, dashboard) depends on it
    for logging, environment variable access, and timing utilities.
    It has NO dependencies on other scraper modules — a clean,
    acyclic dependency graph.
"""

import asyncio  # Python's async/await runtime — provides the event loop
import logging  # Structured logging with severity levels (DEBUG < INFO < WARNING < ERROR < CRITICAL)
import os  # Operating system interface — reads environment variables
import random  # Cryptographically-weak randomness, sufficient for User-Agent rotation

from dotenv import load_dotenv  # Reads .env files into os.environ (pip install python-dotenv)


def load_env():
    """
    Load .env file into os.environ.

    Why this exists:
      The .env file stores secrets (DATABASE_URL). It must NEVER be
      committed to git (it's in .gitignore). This function must be
      called before any code tries to access DATABASE_URL.

    The dotenv library calls os.environ.setdefault() for each
    KEY=VALUE line in .env, so existing environment variables
    from the OS or CI/CD take precedence over .env file values.
    """
    load_dotenv()


def get_database_url() -> str:
    """
    Retrieve the DATABASE_URL connection string from environment variables
    or Streamlit secrets.
    """
    url = os.getenv("DATABASE_URL")
    
    # Fallback to Streamlit secrets if running in Streamlit Cloud
    if not url:
        try:
            import streamlit as st
            url = st.secrets.get("DATABASE_URL")
        except Exception:
            pass

    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Create a .env file or set the variable directly."
        )
    return url


def setup_logging(name: str = "realitycheck", level: int = logging.INFO):
    """
    Configure and return a named logger with consistent formatting.

    Design decisions:
      - Guard clause (if not logger.handlers): Prevents adding duplicate
        handlers when this function is called multiple times for the
        same logger name. Without this, each call to setup_logging()
        would add another StreamHandler, causing duplicate log lines.

      - StreamHandler (stderr): Sends logs to the console. In production
        this would likely be a FileHandler or a cloud logging service
        (e.g., CloudWatch, Datadog).

      - Format string: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        Produces output like:
        2024-03-15 14:30:22 [INFO] scraper.main: Navigating to URL...

    Args:
        name: Logger name (typically __name__ from the calling module).
              This enables per-module log filtering (e.g., you can set
              scraper.parser to DEBUG while keeping scraper.db at INFO).
        level: Minimum severity threshold. Messages below this level
               (e.g., DEBUG messages when level=INFO) are dropped.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


async def random_delay(min_sec: float = 2.0, max_sec: float = 5.0):
    """
    Sleep for a random duration to mimic human browsing behavior.

    This is a critical anti-detection technique:
      - Humans don't click at exactly 3-second intervals
      - Bots (without randomization) produce perfectly uniform timing,
        which is a strong signal to anti-bot systems
      - random.uniform(a, b) returns a float in [a, b) with uniform
        distribution — each value in the range is equally likely

    The default range (2.0–5.0 seconds) is a heuristic chosen to:
      (a) be slower than what feels like a bot
      (b) not be so slow that the scrape takes forever

    'async' keyword: This is a coroutine. It yields control to the
    event loop at 'await asyncio.sleep()', allowing other coroutines
    to make progress while this one is sleeping.
    """
    await asyncio.sleep(random.uniform(min_sec, max_sec))


# What's a User-Agent string?
# Every HTTP request includes a User-Agent header that identifies the
# client software. Websites use this for:
#   - Browser statistics / analytics
#   - Bot detection (if it says "python-requests/2.31.0", it's clearly a bot)
#   - Serving different pages to different browsers
#
# By rotating through real browser User-Agent strings, we make our
# Playwright requests look like legitimate Chrome/Firefox traffic.

USER_AGENTS = [
    # Chrome 120 on Windows 10 — the world's most common browser config
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome 120 on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome 120 on Linux — common for CI/CD runners (GitHub Actions is Ubuntu)
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Firefox 121 on Windows — provides browser diversity
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
    "Gecko/20100101 Firefox/121.0",
]


def get_random_user_agent() -> str:
    """
    Return a randomly selected User-Agent string from the pool.

    random.choice(seq) selects one element with uniform probability
    (each has 1/len(seq) chance). For 4 agents, that's 25% each.

    Note: This is NOT cryptographically secure randomness. For
    security-sensitive applications (session tokens, encryption keys),
    use secrets.choice() instead. But for User-Agent rotation,
    the randomness quality doesn't matter — it just needs to be
    different enough to not look like a pattern.
    """
    return random.choice(USER_AGENTS)
