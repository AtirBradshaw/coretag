import hashlib
import os
import shutil
import subprocess


def safe(fn, default=None):
    """Run one sensor read; a single failing sensor must never sink the run."""
    try:
        return fn()
    except Exception:
        return default


def to_str(v):
    return v.decode(errors="replace") if isinstance(v, bytes) else v


def stable_hash(kind: str, value) -> str | None:
    """A fingerprint that's the same on every run and every machine, so the
    server can recognise the same drive again without publishing its serial."""
    if not value:
        return None
    return hashlib.sha256(f"coretag:{kind}:{value}".encode()).hexdigest()[:32]


def run_cmd(args, timeout=30):
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                             creationflags=flags)
        # smartctl uses bit flags in its exit code; 4 = "some SMART command failed"
        # but the JSON is still usable
        return out.stdout if out.stdout and (out.returncode & 0b11) == 0 else None
    except Exception:
        return None


def find_tool(name, windows_guesses=()):
    found = shutil.which(name) or shutil.which(name + ".exe")
    if found:
        return found
    for guess in windows_guesses:
        if os.path.exists(guess):
            return guess
    return None


def is_admin() -> bool:
    if os.name != "nt":
        return safe(lambda: os.geteuid() == 0, False)
    import ctypes
    return bool(safe(lambda: ctypes.windll.shell32.IsUserAnAdmin(), False))
