"""argo CLI entry point.

M1 scaffolding: prints banner and exits. Real subcommands land in M3 (inherited from
upstream rename) and M4 (`argo update`, `argo doctor`).
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print("argo — usage will be filled in as commands land")
        return 0
    print("argo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
