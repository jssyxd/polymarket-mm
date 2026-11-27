#!/usr/bin/env python3
"""Run the Polymarket maker service.

The service needs no credentials to run in dry-run or paper mode, which is
the mode it starts in on this machine: the account owner's private key is
not available here, so the live-post path stays refused and the runner keeps
going without it.

    python tools/run_mm.py --dry-run --once
    python tools/run_mm.py --paper --interval 5
    python tools/run_mm.py --dry-run --once --replay books.jsonl

Flags:

``--dry-run``
    Journal the order intents, send nothing.
``--paper``
    Watch the live book and record the fills it would have produced. Sends
    nothing.
``--once``
    Run a single cycle and exit.
``--journal``
    Directory the journal lives in.
``--params``
    The parameter file the self-tune step maintains.
``--capital``
    Capital budget for the cycle, in pUSD.
``--size``
    Shares to quote on each side.
``--half-spread``
    Half-spread of the resting quotes, in cents. Written into the parameter
    file so the service and the hourly self-tune agree.
``--interval``
    Seconds between cycles.
``--markets``
    Comma separated condition ids to quote. Empty means the reward pool.
``--top``
    How many candidate markets to pull books for.
``--replay``
    Read the markets from a recorded book file instead of the network.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.core.market import MarketSnapshot  # noqa: E402
from pmm.data.clob import CLOBError  # noqa: E402
from pmm.engine.runner import Runner, RunnerConfig, discover_markets  # noqa: E402
from pmm.engine.self_tune import load_params, write_params  # noqa: E402
from pmm.execution.clob import ExecutionError  # noqa: E402
from pmm.execution.config import ExecutionConfig  # noqa: E402
from pmm.execution.journal import Journal  # noqa: E402

DEFAULT_PARAMS_PATH = "~/.pmm/params.json"
DEFAULT_REPORTS_DIR = "~/.pmm/reports"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket maker service")
    parser.add_argument("--dry-run", action="store_true", help="journal intents, send nothing")
    parser.add_argument("--paper", action="store_true", help="record simulated fills, send nothing")
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--journal", default=None, help="journal directory")
    parser.add_argument("--params", default=None, help="parameter file")
    parser.add_argument("--capital", type=float, default=3.4, help="capital budget in pUSD")
    parser.add_argument("--size", type=float, default=20.0, help="shares per side")
    parser.add_argument("--half-spread", type=float, default=None, help="half-spread in cents")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between cycles")
    parser.add_argument("--markets", default="", help="comma separated condition ids")
    parser.add_argument("--top", type=int, default=10, help="candidate markets to score")
    parser.add_argument("--min-rate", type=float, default=50.0, help="minimum reward rate per day")
    parser.add_argument("--max-spread", type=float, default=4.5, help="maximum reward spread band, cents")
    parser.add_argument("--replay", default=None, help="replay a recorded book file")
    parser.add_argument("--reports", default=DEFAULT_REPORTS_DIR, help="report directory")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> ExecutionConfig:
    """The execution config, with the CLI's choices applied."""
    config = ExecutionConfig.from_env()
    if args.journal:
        config.journal_path = args.journal
    if args.dry_run or args.paper:
        config.dry_run = True
    return config


def replay_source(path: str):
    """Read the markets from a recorded book file."""
    records: list[MarketSnapshot] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if not isinstance(payload, dict):
                continue
            records.append(MarketSnapshot(**{
                key: value
                for key, value in payload.items()
                if key in MarketSnapshot.__dataclass_fields__
            }))
    return lambda: [(snapshot, None) for snapshot in records]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    config = build_config(args)
    params_path = args.params or DEFAULT_PARAMS_PATH
    params = load_params(params_path)
    if args.half_spread is not None:
        params["half_spread_cents"] = float(args.half_spread)
        write_params(params_path, params)

    runner_config = RunnerConfig(
        capital_usd=args.capital,
        size_shares=args.size,
        interval_seconds=args.interval,
        top=args.top,
        paper=args.paper,
        min_rate_per_day=args.min_rate,
        max_spread_cents_cap=args.max_spread,
    )

    journal = Journal(config.journal_path)
    condition_ids = [part.strip() for part in args.markets.split(",") if part.strip()]

    if args.replay:
        source = replay_source(args.replay)
    else:
        half_spread = float(params.get("half_spread_cents", 1.0) or 1.0)
        source = lambda: discover_markets(runner_config, half_spread, condition_ids)

    runner = Runner(
        config,
        runner_config,
        params_path=params_path,
        params=params,
        journal=journal,
        market_source=source,
    )

    try:
        if args.once:
            try:
                outcome = runner.run_once()
                print(outcome["summary"])
            except (CLOBError, ExecutionError) as exc:
                logging.getLogger("pmm.runner").error("cycle failed: %s", exc)
                journal.append("error", kind_of_error=type(exc).__name__, error=str(exc))
                print(
                    f"cycle failed: {exc} | markets=0 quoted=0 intents=0 "
                    f"committed=0.000/{runner_config.capital_usd:.3f} pUSD hard_stops=0"
                )
        else:
            runner.run_forever()
    except KeyboardInterrupt:
        runner.stop()
    finally:
        runner.shutdown()

    print(f"journal: {config.journal_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
