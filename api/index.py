"""
Vercel Python entrypoint shim.

Keeps `api/monitor.py` as the implementation while exposing a conventional
`api/index.py` entrypoint so Vercel detects Python runtime reliably.
"""

from api.monitor import handler  # noqa: F401
