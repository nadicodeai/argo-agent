"""
Argo CLI - Unified command-line interface for Argo Agent.

Provides subcommands for:
- argo chat          - Interactive chat (same as ./argo)
- argo gateway       - Run gateway in foreground
- argo gateway start - Start gateway service
- argo gateway stop  - Stop gateway service
- argo setup         - Interactive setup wizard
- argo status        - Show status of all components
- argo cron          - Manage cron jobs
"""

import os
import sys

__version__ = "0.14.0"
__release_date__ = "2026.5.16"


def _ensure_utf8():
    """Force UTF-8 stdout/stderr on Windows to prevent UnicodeEncodeError.

    Windows services and terminals default to cp1252, which cannot encode
    box-drawing characters used in CLI output. This causes unhandled
    UnicodeEncodeError crashes on gateway startup.
    """
    if sys.platform != "win32":
        return
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            if getattr(stream, "encoding", "").lower().replace("-", "") != "utf8":
                new_stream = open(
                    stream.fileno(), "w", encoding="utf-8",
                    buffering=1, closefd=False,
                )
                setattr(sys, stream_name, new_stream)
        except (AttributeError, OSError):
            pass


_ensure_utf8()
