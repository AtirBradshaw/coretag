"""Hardware collectors.

Each collector returns (components, problems):
    components  list of dicts, each with a "kind" ("gpu", "drive", ...)
    problems    list of plain-English strings to show the user if something
                couldn't be read (missing tool, needs admin, etc.)

To support a new kind of part, add a module here with a `collect()`
function and list it in COLLECTORS. The server needs a matching scorer.
"""

from . import gpu_nvidia, storage

COLLECTORS = [gpu_nvidia.collect, storage.collect]


def collect_all():
    components, problems = [], []
    for fn in COLLECTORS:
        try:
            c, p = fn()
        except Exception as e:  # a broken collector must not stop the others
            c, p = [], [f"{fn.__module__}: {type(e).__name__}: {e}"]
        components.extend(c)
        problems.extend(p)
    return components, problems
