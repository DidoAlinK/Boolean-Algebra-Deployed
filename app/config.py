"""Limits in one place so they are easy to find and change."""
import os


def _max_variables() -> int:
    """Default 12 (4096 truth-table rows). Override with BOOLEAN_LAB_MAX_VARIABLES, hard-capped at 16
    because the table has 2**n rows: 16 variables is already 65,536 rows and 26 would be 67 million."""
    try:
        wanted = int(os.environ.get("BOOLEAN_LAB_MAX_VARIABLES", "12"))
    except ValueError:
        wanted = 12
    return max(1, min(wanted, 16))


MAX_EXPRESSION_LENGTH = 300   # characters accepted per request
MAX_VARIABLES = _max_variables()   # truth table has 2**n rows
MAX_NESTING = 100             # nested brackets / chained prefix operators
MAX_CIRCUIT_NODES = 400       # beyond this the circuit is skipped with a warning
KMAP_MAX_VARIABLES = 4        # K-map is drawn for 1 to 4 variables


# -- simplifier ---------------------------------------------------------------------------------
def _env_number(name: str, default: float, low: float, high: float) -> float:
    """Reads a number from the environment, falls back to the default when missing or invalid, and keeps
    it between low and high so a typo cannot switch a protection off."""
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        value = default
    return max(low, min(value, high))


MAX_SIMPLIFY_LENGTH = int(_env_number("BOOLEAN_LAB_MAX_SIMPLIFY_LENGTH", 2000, 50, 5000))  # characters
SIMPLIFY_SECONDS = _env_number("BOOLEAN_LAB_SIMPLIFY_SECONDS", 3.0, 0.5, 20)   # time budget per request
SIMPLIFY_MAX_STEPS = 300                                                       # steps in one answer
SIMPLIFY_MAX_NODES = 3000                                                      # size of the tree while working
SIMPLIFY_MAX_PARALLEL = int(_env_number("BOOLEAN_LAB_SIMPLIFY_PARALLEL", 2, 1, 16))  # at the same moment

# -- protection: body size and rate limits ------------------------------------------------------
MAX_BODY_BYTES = int(_env_number("BOOLEAN_LAB_MAX_BODY_BYTES", 32 * 1024, 1024, 1024 * 1024))

# (path prefix, requests allowed, per how many seconds). Per client address. The first prefix that
# matches wins, so the specific paths come before the general "/api/" one.
RATE_LIMITS: list[tuple[str, int, int]] = [
    ("/api/simplify", int(_env_number("BOOLEAN_LAB_RATE_SIMPLIFY", 15, 1, 10000)), 60),
    ("/api/analyze", int(_env_number("BOOLEAN_LAB_RATE_ANALYZE", 120, 1, 10000)), 60),
    ("/api/synthesize", int(_env_number("BOOLEAN_LAB_RATE_SYNTHESIZE", 60, 1, 10000)), 60),
    ("/api/", int(_env_number("BOOLEAN_LAB_RATE_OTHER", 240, 1, 10000)), 60),
]
# Set to 1 ONLY when the app runs behind ONE reverse proxy that adds X-Forwarded-For. Otherwise every
# visitor would look like the proxy itself (one shared limit) or, worse, a visitor could fake the header.
TRUST_PROXY = os.environ.get("BOOLEAN_LAB_TRUST_PROXY", "") == "1"
# Name of a header that carries the real client address when the app is only reachable through a CDN that
# sets it (Render sits behind Cloudflare: "cf-connecting-ip"). Empty = not used.
CLIENT_IP_HEADER = os.environ.get("BOOLEAN_LAB_CLIENT_IP_HEADER", "").strip().lower()
