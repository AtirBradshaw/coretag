"""Coretag agent: reads PC component sensors and firmware, read-only.

The agent only COLLECTS. It never scores, never decides a verdict, and never
summarises the load test. It sends raw readings; the server does the rest.
"""

VERSION = "0.2.0"
SCHEMA = 2
