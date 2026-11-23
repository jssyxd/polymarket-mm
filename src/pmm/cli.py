"""Console entry points.

The scripts under ``tools/`` are the working interface. These wrappers exist
so the service can be started from a systemd unit without depending on the
repository layout, and so the two commands have one definition each.
"""

from __future__ import annotations

import sys

__all__ = ["run_mm", "selftune"]


def run_mm(argv: list[str] | None = None) -> int:
    """Start the maker service."""
    from tools.run_mm import main  # noqa: PLC0415

    return main(argv)


def selftune(argv: list[str] | None = None) -> int:
    """Run one self-tune tick."""
    from tools.selftune import main  # noqa: PLC0415

    return main(argv)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run_mm())
