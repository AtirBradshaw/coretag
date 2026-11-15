"""Short, human-friendly codes for reports, parts and comparisons.

Current format: two words, an adjective and a noun, like `amber-otter`.
Easy to read aloud, write on a slip of paper, or type on a phone.

If the two-word space ever gets crowded, the generator automatically adds a
number (`amber-otter-42`), so a code can always be issued. Existing codes never
change.

Older codes (six characters like `U9PNUK`, from before word codes) keep working
forever: `normalize` recognises both formats.
"""

import re
import secrets

from .words import ADJECTIVES, NOUNS

_ADJ = frozenset(ADJECTIVES)
_NOUN = frozenset(NOUNS)

# --- legacy six-character codes (no 0/O, 1/I/L, 2/Z, 5/S, 8/B)
LEGACY_ALPHABET = "ACDEFGHJKMNPQRTUVWXY34679"
LEGACY_LENGTH = 6

MAX_CODE_LENGTH = 32


def new_id(digits: int = 0) -> str:
    """A random code: `adjective-noun`, plus `-NN...` if digits > 0."""
    code = f"{secrets.choice(ADJECTIVES)}-{secrets.choice(NOUNS)}"
    if digits:
        code += f"-{secrets.randbelow(10 ** digits):0{digits}d}"
    return code


def _split_joined(word: str):
    """'amberotter' -> ('amber', 'otter'), for people who skip the dash."""
    for i in range(3, len(word) - 2):
        if word[:i] in _ADJ and word[i:] in _NOUN:
            return word[:i], word[i:]
    return None


def normalize(code: str | None) -> str | None:
    """Turn whatever a person typed into the stored form, or None if it can't
    be a Coretag code. Accepts 'Amber Otter', 'amber_otter', 'AMBER-OTTER',
    'amberotter', 'amber otter 42', and old codes like 'u9p-nuk'."""
    if not isinstance(code, str):
        return None
    raw = code.strip()
    if not raw or len(raw) > 40:
        return None

    # --- word codes
    s = re.sub(r"[\s_.,/]+", "-", raw.lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    s = re.sub(r"^([a-z]+?)(\d+)$", r"\1-\2", s)          # 'amberotter42'
    parts = s.split("-")
    number = None
    if len(parts) > 1 and parts[-1].isdigit():
        number = parts.pop()
    words = None
    if len(parts) == 2 and parts[0] in _ADJ and parts[1] in _NOUN:
        words = (parts[0], parts[1])
    elif len(parts) == 1:
        words = _split_joined(parts[0])
    if words and (number is None or 1 <= len(number) <= 4):
        return "-".join(words) + (f"-{number}" if number else "")

    # --- legacy six-character codes
    legacy = raw.upper().replace("-", "").replace(" ", "")
    if len(legacy) == LEGACY_LENGTH and all(ch in LEGACY_ALPHABET for ch in legacy):
        return legacy
    return None
