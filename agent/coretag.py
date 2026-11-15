#!/usr/bin/env python3
"""
================================================================
 CORETAG  -  measured health reports for used PC components
================================================================
Double-click this file to start, or run:  python coretag.py

READ-ONLY. Every value comes from an interface the manufacturer provides:
  * NVIDIA GPUs  ->  NVML, NVIDIA's own management library
  * Drives       ->  smartctl (smartmontools)
The load test renders arithmetic offscreen: nothing is drawn on screen,
nothing is written to the card, no data on your drives is touched.

Source-available. See LICENSE.txt. This is not open source.
================================================================
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NEEDED = (("pynvml", "nvidia-ml-py"), ("moderngl", "moderngl"), ("numpy", "numpy"))


def ensure_deps():
    """Install the three libraries Coretag needs on first run, so nobody has
    to touch pip. (The packaged Windows app will make this unnecessary.)"""
    missing = []
    for mod, pkg in NEEDED:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if not missing:
        return
    print("First run: installing " + ", ".join(missing) + " (about a minute, once only)...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet",
                    "--disable-pip-version-check"] + missing, timeout=600)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()   # the load test runs in a helper process
    ensure_deps()
    from coretag_agent.cli import run
    sys.exit(run())
