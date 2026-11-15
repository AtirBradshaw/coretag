"""Short, human-typeable IDs for reports, claim codes and comparisons.

The alphabet leaves out characters people confuse when reading or typing
them from a phone screen or a slip of paper: 0/O, 1/I/L, 2/Z, 5/S, 8/B.
25 symbols, 6 characters = ~244 million possible IDs.
"""

import secrets

ALPHABET = "ACDEFGHJKMNPQRTUVWXY34679"
LENGTH = 6


def new_id(length: int = LENGTH) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def normalize(code: str | None) -> str | None:
    """Accept what a person might type: lower case, spaces, dashes."""
    if not isinstance(code, str):
        return None
    c = code.strip().upper().replace("-", "").replace(" ", "")
    if len(c) != LENGTH or any(ch not in ALPHABET for ch in c):
        return None
    return c
