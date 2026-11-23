#!/usr/bin/env python3
"""Run one hourly self-tune tick.

Reads the journal, asks the monitor agent for at most one parameter change,
writes the parameters back atomically, and writes the hourly report. The
runner reads the parameter file at the top of every cycle, so this is the
half of the system that makes the quoting adapt.

    python tools/selftune.py --journal ~/.pmm/journal --params ~/.pmm/params.json

An empty journal is not an error: no fills means no evidence, the parameters
are held, and the report says so.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.engine.self_tune import load_params, run_self_tune  # noqa: E402

DEFAULT_JOURNAL = os.environ.get("POLY_JOURNAL_PATH", "~/.pmm/journal")
DEFAULT_PARAMS = os.environ.get("POLY_PARAMS_PATH", "~/.pmm/params.json")
DEFAULT_REPORTS = os.environ.get("POLY_REPORTS_DIR", "~/.pmm/reports")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", default=DEFAULT_JOURNAL, help="journal directory")
    parser.add_argument("--params", default=DEFAULT_PARAMS, help="parameter file")
    parser.add_argument("--reports", default=DEFAULT_REPORTS, help="report directory")
    args = parser.parse_args(argv)

    result = run_self_tune(
        os.path.expanduser(args.journal),
        os.path.expanduser(args.params),
        os.path.expanduser(args.reports),
    )
    print(
        json.dumps(
            {
                "changed": result.decision.get("changed"),
                "action": result.decision.get("action"),
                "param": result.decision.get("param"),
                "from_value": result.decision.get("from_value"),
                "to_value": result.decision.get("to_value"),
                "reason": result.decision.get("reason"),
                "fills": len(result.fills),
                "report": result.report_path,
                "params": result.params,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
