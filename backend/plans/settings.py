"""Plan settings, read at call time."""

import os


def free_max() -> bool:
    """The suite is free (the default): a hosted account with a confirmed email is on Max
    (plans.of) and nothing is sold. FREE_MAX=false goes back to the plan limits (caps.py)."""
    return os.environ.get("FREE_MAX", "").strip().lower() not in ("0", "false", "no", "off")
