"""Gemini account token rotation.

Stores 3 account tokens:
  ~/.gemini/account_1.json  (primary)
  ~/.gemini/account_2.json  (fallback)
  ~/.gemini/account_3.json  (fallback)

State file: ~/.gemini/current_account_idx  (0, 1, or 2)

rotate_account() copies the next account's token to oauth_creds.json.
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger("GeminiTokenRotator")

GEMINI_DIR = Path.home() / ".gemini"
STATE_FILE = GEMINI_DIR / "current_account_idx"
CREDS_FILE = GEMINI_DIR / "oauth_creds.json"
ACCOUNT_FILES = [
    GEMINI_DIR / "account_1.json",
    GEMINI_DIR / "account_2.json",
    GEMINI_DIR / "account_3.json",
]


def _read_idx() -> int:
    try:
        return int(STATE_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0


def _write_idx(idx: int):
    STATE_FILE.write_text(str(idx))


def current_account_label() -> str:
    """Return human-readable label for the active account."""
    idx = _read_idx()
    return f"account_{idx + 1}"


def rotate_account() -> str:
    """Rotate to the next available account and update oauth_creds.json.

    Returns the label of the newly active account, or None if no accounts exist.
    """
    idx = _read_idx()
    available = [p for p in ACCOUNT_FILES if p.exists()]

    if not available:
        logger.warning("No account token files found at %s", GEMINI_DIR)
        return None

    # Try next account, wrap around
    for attempt in range(len(available)):
        idx = (idx + 1) % len(ACCOUNT_FILES)
        src = ACCOUNT_FILES[idx]
        if src.exists():
            shutil.copy2(str(src), str(CREDS_FILE))
            _write_idx(idx)
            label = f"account_{idx + 1}"
            logger.info("Rotated to %s (%s)", label, src)
            return label

    logger.warning("No valid account files found to rotate to")
    return None


def ensure_account_1() -> str:
    """Ensure the primary account (account_1) is active in oauth_creds.json."""
    idx = _read_idx()
    if idx == 0 and CREDS_FILE.exists():
        return "account_1"

    src = ACCOUNT_FILES[0]
    if not src.exists():
        logger.warning("account_1.json not found, cannot set primary")
        return None

    shutil.copy2(str(src), str(CREDS_FILE))
    _write_idx(0)
    logger.info("Set active account to account_1")
    return "account_1"


def is_quota_exhausted(stderr_text: str) -> bool:
    """Check if stderr contains a quota exhaustion error."""
    markers = (
        "quota_exhausted",
        "exhausted",
        "quota",
        "429",
        "capacity",
    )
    return any(m in stderr_text.lower() for m in markers) if stderr_text else False


if __name__ == "__main__":
    print(f"Current: {current_account_label()}")
    print(f"Rotating... → {rotate_account()}")
    print(f"Now active: {current_account_label()}")
