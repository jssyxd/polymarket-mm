"""The service loop: one quote cycle, then sleep, then the next cycle.

The runner owns everything that has to live in one process.

The heartbeat lives here, not in a separate service. The first accepted
heartbeat arms the venue's timeout cancellation for every open order on the
API key, and there is no disarm endpoint, so a heartbeat process that dies
takes the whole book down. One process, one heartbeat, one order placer.

The shutdown order is fixed and it matters. The runner cancels all orders
first, then stops the heartbeat, then closes the client. Stopping the
heartbeat first would leave a window where the venue cancels everything on
its own, without the runner knowing what was cancelled.

A cycle that fails does not take the service down. A network error or an
execution error is logged, the runner waits, and the next cycle runs.

Paper mode watches the live book and records the fill the book would have
produced against our resting quote. Nothing is ever sent to the exchange.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..core.inventory import PairedInventory
from ..core.market import MarketSnapshot
from ..core.selection import QuoteIntent
from ..data.clob import CLOBError, get_book, get_market, get_midpoint, list_reward_markets
from ..data.universe import RewardCandidate, market_meta, score_candidate
from ..execution.clob import ExecutionError, Heartbeat, OrderExecutor
from ..execution.positions import read_positions
from ..execution.trades import sync_fills
from ..execution.config import ExecutionConfig
from ..execution.journal import Journal, compute_pnl
from .cycle import QuoteCycle
from .self_tune import load_params, net_capture_series

__all__ = [
    "MarketSource",
    "PositionSource",
    "Runner",
    "RunnerConfig",
    "discover_markets",
]

LOGGER = logging.getLogger("pmm.runner")

#: Plan B floor: a harvest sell never rests below this price.
HARVEST_MIN_PRICE = 0.99


#: The key a resting order is tracked under. The side is part of it.
def _resting_key(intent: QuoteIntent) -> tuple[str, str, str]:
    return (intent.condition_id, intent.leg, intent.side.upper())


#: A callable that returns the markets to quote this cycle.
MarketSource = Callable[[], Sequence[tuple[MarketSnapshot, RewardCandidate]]]

#: A callable that returns the account's open positions, keyed by token id.
PositionSource = Callable[[], Mapping[str, float]]


def _venue_positions(config: ExecutionConfig) -> PositionSource:
    """Read the held size per token id from the venue's positions endpoint."""

    def read() -> Mapping[str, float]:
        rows = read_positions(config).get("api_positions") or []
        return {
            str(row.get("token_id")): float(row.get("current_size") or 0.0)
            for row in rows
            if isinstance(row, dict) and row.get("token_id")
        }

    return read


@dataclass
class RunnerConfig:
    """The service settings that are not credentials.

    Attributes:
        capital_usd: Capital budget for the cycle.
        size_shares: Shares to quote on each side.
        interval_seconds: Seconds between cycles.
        top: How many candidate markets to pull books for.
        min_rate_per_day: Lowest daily reward rate a market must clear.
        max_spread_cents_cap: Highest reward spread band a market may have.
        paper: Record simulated fills, never send anything.
        reprice_ticks: How far the book may move before a quote is replaced.
        max_markets: How many markets a cycle may quote at once.
    """

    capital_usd: float = 3.4
    size_shares: float = 20.0
    interval_seconds: float = 5.0
    top: int = 10
    min_rate_per_day: float = 50.0
    max_spread_cents_cap: float = 4.5
    paper: bool = False
    reprice_ticks: float = 1.0
    max_markets: int = 4


def _rate_of(row: dict) -> float:
    configs = row.get("rewards_config") or ()
    rates = [
        float(config["rate_per_day"])
        for config in configs
        if isinstance(config, dict) and "rate_per_day" in config
    ]
    if rates:
        return max(rates)
    return float(row.get("native_daily_rate") or 0.0)


def _best_ask(book: Mapping[str, Any]) -> float:
    """The lowest ask in a raw CLOB book, or 0.0 when there is none."""
    asks = book.get("asks") or ()
    prices = []
    for entry in asks:
        try:
            prices.append(float(entry["price"]))
        except (KeyError, TypeError, ValueError):
            continue
    return min(prices) if prices else 0.0


def discover_markets(
    config: RunnerConfig,
    half_spread_cents: float,
    condition_ids: Sequence[str] | None = None,
) -> list[tuple[MarketSnapshot, RewardCandidate]]:
    """Find the markets to quote this cycle.

    With no ``condition_ids`` the reward markets are listed and the most
    profitable ones are pulled first. With ``condition_ids`` only those
    markets are read.
    """
    if condition_ids:
        rows = []
        for condition_id in condition_ids:
            rows.append({"condition_id": condition_id})
    else:
        rows = list_reward_markets()
        pool = [
            row
            for row in rows
            if _rate_of(row) >= config.min_rate_per_day
            and float(row.get("rewards_max_spread") or 0.0) <= config.max_spread_cents_cap
            and float(row.get("rewards_min_size") or 0.0) <= config.size_shares
        ]
        pool.sort(key=_rate_of, reverse=True)
        rows = pool[: config.top]

    found: list[tuple[MarketSnapshot, RewardCandidate]] = []
    for row in rows:
        condition_id = str(row.get("condition_id", ""))
        if not condition_id:
            continue
        try:
            market = get_market(condition_id)
            tokens = [str(token["token_id"]) for token in market.get("tokens") or ()]
            if len(tokens) != 2:
                continue
            book_up = get_book(tokens[0])
            book_down = get_book(tokens[1])
            mid_up = get_midpoint(tokens[0])
            mid_down = get_midpoint(tokens[1])
        except (CLOBError, KeyError, TypeError, ValueError) as exc:
            LOGGER.warning("skipping market %s: %s", condition_id, exc)
            continue

        meta = market_meta(market, rewards_row=row if "rewards_min_size" in row else None)
        spread = min(half_spread_cents, float(meta["max_spread_cents"]) or half_spread_cents)
        candidate = score_candidate(
            meta,
            book_up,
            book_down,
            mid_up,
            mid_down,
            config.size_shares,
            spread,
        )
        snapshot = MarketSnapshot.from_clob_market(
            market,
            book_up=book_up,
            book_down=book_down,
            rewards_row=row if "rewards_min_size" in row else None,
            rate_per_day=candidate.rate_per_day,
            midpoint=mid_up,
        )
        found.append((snapshot, candidate))
    return found


class Runner:
    """The service: cycles, orders, heartbeat, reconciliation, shutdown."""

    def __init__(
        self,
        config: ExecutionConfig,
        runner_config: RunnerConfig,
        *,
        params_path: str | Path,
        params: Mapping[str, Any] | None = None,
        journal: Journal | None = None,
        cycle: QuoteCycle | None = None,
        executor: OrderExecutor | None = None,
        heartbeat: Heartbeat | None = None,
        market_source: MarketSource | None = None,
        positions_source: PositionSource | None = None,
    ) -> None:
        self.config = config
        self.runner_config = runner_config
        self.params_path = str(params_path)
        self.params = dict(params or load_params(self.params_path))
        self.journal = journal if journal is not None else Journal(config.journal_path)
        self.cycle = cycle if cycle is not None else QuoteCycle(
            min_rate_per_day=runner_config.min_rate_per_day,
            max_spread_cents_cap=runner_config.max_spread_cents_cap,
            max_markets=runner_config.max_markets,
        )
        self.executor = executor if executor is not None else OrderExecutor(config, self.journal)
        self.heartbeat = heartbeat
        self.market_source = market_source
        self.positions_source = (
            positions_source
            if positions_source is not None or config.dry_run
            else _venue_positions(config)
        )

        # Keyed by (condition, leg, side): a harvest sell may rest on the
        # same leg as a quote buy, and the two must not cancel each other.
        self._resting: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._paper_filled: set[tuple[str, str, float]] = set()
        self._running = False
        self.live_refused = False
        self._refusal_announced = False

    # -- startup ----------------------------------------------------------

    def announce(self) -> None:
        """Say once that live orders are refused, then keep going."""
        if self._refusal_announced:
            return
        self._refusal_announced = True
        if not self.config.has_owner_key:
            self.live_refused = True
            mode = "paper" if self.runner_config.paper else "dry-run"
            LOGGER.warning(
                "no owner private key: refusing to place live orders, "
                "continuing in %s mode",
                mode,
            )

    def start(self) -> None:
        """Start the heartbeat, if this mode has one.

        The heartbeat is refused in dry-run mode, and it needs the L2
        credentials, so it only exists on the live path.
        """
        self.announce()
        if self.heartbeat is None and not self.config.dry_run and self.config.has_credentials:
            self.heartbeat = Heartbeat(self.config, journal=self.journal)
        if self.heartbeat is not None and not self.config.dry_run:
            self.heartbeat.start()
        self._running = True

    def stop(self) -> None:
        """Ask the loop to end after the current cycle."""
        self._running = False

    # -- state ------------------------------------------------------------

    def _inventory(
        self, pairs: Sequence[tuple[MarketSnapshot, RewardCandidate]]
    ) -> dict[str, PairedInventory]:
        """Positions per market, from the venue when live, else the journal.

        A live fill is not written to the journal (only paper fills are), so a
        journal-only view reports an empty book while shares are already held.
        That makes the inventory box gate blind exactly when it matters, and
        the cycle keeps quoting as if it were flat. `positions_source` returns
        the held size per token id; the journal stays the fallback.
        """
        shares: Mapping[str, float] | None = None
        if self.positions_source is not None:
            try:
                shares = self.positions_source()
            except Exception as exc:  # noqa: BLE001 - the book is advisory
                LOGGER.warning("venue positions unavailable, using the journal: %s", exc)
        fills = self.journal.fills()
        marks: dict[str, float] = {}
        for snapshot, _ in pairs:
            marks[snapshot.up_token_id] = snapshot.midpoint
            marks[snapshot.down_token_id] = 1.0 - snapshot.midpoint
        positions = compute_pnl(fills, marks).get("positions", {}) if fills else {}
        box = float(self.params.get("inventory_box", 0.0) or 0.0)
        inventory: dict[str, PairedInventory] = {}
        for snapshot in pairs:
            snapshot = snapshot[0] if isinstance(snapshot, tuple) else snapshot
            if shares is not None:
                up_shares = float(shares.get(str(snapshot.up_token_id), 0.0) or 0.0)
                down_shares = float(shares.get(str(snapshot.down_token_id), 0.0) or 0.0)
            else:
                row = positions.get(snapshot.condition_id, {})
                up_shares = float(row.get("up_shares", 0.0) or 0.0)
                down_shares = float(row.get("down_shares", 0.0) or 0.0)
            inventory[snapshot.condition_id] = PairedInventory(
                up_shares=up_shares,
                down_shares=down_shares,
                max_inventory_per_side=box,
                mark_up=snapshot.midpoint,
                mark_down=1.0 - snapshot.midpoint,
            )
        return inventory

    def _last_fills(self) -> dict[str, tuple[str | None, float | None]]:
        """The most recent fill per market."""
        last: dict[str, tuple[str | None, float | None]] = {}
        for fill in self.journal.fills():
            condition_id = str(fill.get("condition_id", ""))
            if not condition_id:
                continue
            outcome = str(fill.get("outcome", "")).strip().lower()
            side = "up" if outcome in ("up", "yes", "higher") else "down"
            stamp = fill.get("ts")
            parsed: float | None = None
            if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
                parsed = float(stamp)
            elif isinstance(stamp, str):
                try:
                    from datetime import datetime

                    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    parsed = None
            last[condition_id] = (side, parsed)
        return last

    # -- reconciliation ---------------------------------------------------

    def _cancel_resting(
        self, key: tuple[str, str], resting: Mapping[str, Any], reason: str
    ) -> None:
        """Cancel one resting quote and forget it."""
        order_id = resting.get("order_id")
        if order_id:
            try:
                self.executor.cancel(str(order_id))
            except ExecutionError as exc:
                LOGGER.warning("cancel failed for %s: %s", key, exc)
        self.journal.append(
            "cancel",
            condition_id=key[0],
            leg=key[1],
            price=resting.get("price"),
            reason=reason,
            scope="leg",
        )
        self._resting.pop(key, None)

    def _reconcile(self, intents: Sequence[QuoteIntent]) -> None:
        """Match the resting quotes against the new ones.

        A quote that still sits at the right price keeps its place in the
        book. A quote the market has moved away from is cancelled and
        replaced, because the venue does not let us amend a resting order.
        """
        wanted = {_resting_key(intent): intent for intent in intents}
        for key, resting in list(self._resting.items()):
            intent = wanted.get(key)
            if intent is None:
                self._cancel_resting(key, resting, "market_not_quoted")
                continue
            tick = max(intent.tick_size, 1e-9)
            drift = abs(intent.price - float(resting.get("price", 0.0)))
            if drift > self.runner_config.reprice_ticks * tick + 1e-12:
                self._cancel_resting(key, resting, "price_drift")

    # -- placement --------------------------------------------------------

    @staticmethod
    def _payloads(intents: Sequence[QuoteIntent]) -> list[dict[str, Any]]:
        """Turn intents into execution payloads, refusing anything not post-only.

        The venue rejects a crossing order, and a crossing order on one leg
        breaks the pair the maker is built on. Post-only is not a preference
        here, it is the invariant.
        """
        payloads: list[dict[str, Any]] = []
        for intent in intents:
            if not intent.post_only:
                raise ExecutionError(
                    f"intent for {intent.condition_id}/{intent.leg} is not post-only"
                )
            side = intent.side.upper()
            if getattr(intent, "kind", "quote") == "harvest":
                # Plan B: the only sell the system may rest. It exists to
                # convert a nearly-won leg into cash instead of waiting for
                # resolution, and it must never be mistaken for a quote.
                if side != "SELL":
                    raise ExecutionError(
                        f"harvest intent for {intent.condition_id}/{intent.leg} must be a sell"
                    )
                if intent.price < HARVEST_MIN_PRICE:
                    raise ExecutionError(
                        f"harvest sell at {intent.price} is below the {HARVEST_MIN_PRICE} floor"
                    )
                if intent.size <= 0:
                    raise ExecutionError("harvest sell with no size")
                payloads.append(intent.to_payload())
                continue
            if side != "BUY":
                raise ExecutionError(
                    f"intent for {intent.condition_id}/{intent.leg} is not a buy: "
                    "the maker rests two bids, never a bid and an ask"
                )
            payloads.append(intent.to_payload())
        return payloads

    @staticmethod
    def _affordable(
        intents: Sequence[QuoteIntent], balance_pusd: float | None
    ) -> tuple[list[QuoteIntent], list[QuoteIntent]]:
        """Split intents into the ones the balance can fund and the rest.

        A BUY reserves `price * size` of collateral at the venue, so two legs
        of a pair reserve their sum, not the cheaper leg. The selector's
        budget model is the merge-funded one and can therefore over-commit
        once the real balance is lower than the configured budget. `None`
        means the balance could not be read, and every intent is kept.
        """
        if balance_pusd is None:
            return list(intents), []
        kept: list[QuoteIntent] = []
        dropped: list[QuoteIntent] = []
        spent = 0.0
        for intent in intents:
            cost = float(intent.price) * float(intent.size)
            if spent + cost <= balance_pusd + 1e-6:
                kept.append(intent)
                spent += cost
            else:
                dropped.append(intent)
        return kept, dropped

    def _place(self, intents: Sequence[QuoteIntent]) -> None:
        """Send the intents that are not already resting."""
        fresh = [
            intent
            for intent in intents
            if _resting_key(intent) not in self._resting
        ]
        if not fresh:
            return
        balance = None if self.config.dry_run else self.executor.collateral_balance()
        fresh, unaffordable = self._affordable(fresh, balance)
        if unaffordable:
            self.journal.append(
                "order_skipped",
                reason="insufficient_collateral",
                balance=balance,
                intents=[
                    {
                        "condition_id": intent.condition_id,
                        "leg": intent.leg,
                        "price": intent.price,
                        "size": intent.size,
                    }
                    for intent in unaffordable
                ],
            )
        if not fresh:
            return
        payloads = self._payloads(fresh)
        reason = "paired_bid"
        results = self.executor.place_batch(payloads, reason=reason)
        for intent, result in zip(fresh, results):
            order_id = ""
            if isinstance(result, dict):
                order_id = str(result.get("orderID") or result.get("order_id") or "")
            self._resting[_resting_key(intent)] = {
                "price": intent.price,
                "size": intent.size,
                "order_id": order_id,
            }

    def _sync_fills(self) -> None:
        """Record the venue's fills. Live only: a paper run fills nothing."""
        if self.config.dry_run:
            return
        try:
            fresh = sync_fills(self.journal, self.config)
        except Exception as exc:  # noqa: BLE001 - never stop a cycle
            LOGGER.warning("fill sync failed: %s", exc)
            return
        for fill in fresh:
            LOGGER.info(
                "fill %s %s %.4f @ %.4f on %s",
                fill.get("side"),
                fill.get("outcome"),
                float(fill.get("size") or 0.0),
                float(fill.get("price") or 0.0),
                str(fill.get("condition_id"))[:10],
            )

    # -- paper mode -------------------------------------------------------

    def _record_paper_fills(
        self, intents: Sequence[QuoteIntent], pairs: Sequence[tuple[MarketSnapshot, RewardCandidate]]
    ) -> None:
        """Record the fills the live book would have produced.

        A resting bid at price P is filled when the book offers to sell at P
        or better. Nothing is sent to the exchange.
        """
        books = {snapshot.condition_id: snapshot for snapshot, _ in pairs}
        for intent in intents:
            snapshot = books.get(intent.condition_id)
            if snapshot is None:
                continue
            book = snapshot.book_up if intent.leg == "up" else snapshot.book_down
            ask = _best_ask(book)
            if ask <= 0.0 or ask > intent.price + 1e-12:
                continue
            key = (intent.condition_id, intent.leg, round(intent.price, 6))
            if key in self._paper_filled:
                continue
            self._paper_filled.add(key)
            self.journal.append(
                "fill",
                condition_id=intent.condition_id,
                token_id=intent.token_id,
                outcome="Up" if intent.leg == "up" else "Down",
                side="BUY",
                price=intent.price,
                size=intent.size,
                notional=intent.price * intent.size,
                paper=True,
                book_ask=ask,
            )

    # -- one cycle --------------------------------------------------------

    def run_once(self) -> dict[str, Any]:
        """Run one cycle and return the cycle summary."""
        self.announce()
        self.params = load_params(self.params_path)

        if self.market_source is not None:
            pairs = list(self.market_source())
        else:
            half_spread = float(self.params.get("half_spread_cents", 1.0) or 1.0)
            pairs = discover_markets(self.runner_config, half_spread)

        snapshots = [snapshot for snapshot, _ in pairs]
        candidates = [candidate for _, candidate in pairs]

        result = self.cycle.run(
            snapshots,
            self.params,
            candidates=candidates,
            inventory=self._inventory(pairs),
            last_fills=self._last_fills(),
            recent_net_bps=net_capture_series(self.journal.fills()),
            capital_usd=self.runner_config.capital_usd,
            size_shares=self.runner_config.size_shares,
            equity_usd=self.runner_config.capital_usd,
        )

        self._reconcile(result.intents)
        self._place(result.intents)
        self._sync_fills()
        if self.runner_config.paper:
            self._record_paper_fills(result.intents, pairs)

        summary = result.summary()
        self.journal.append(
            "cycle",
            summary=summary,
            quoted=result.quoted,
            intents=len(result.intents),
            committed_usd=result.committed_usd,
            hard_stops=result.hard_stops,
            rejected=result.rejected,
        )
        return {
            "summary": summary,
            "intents": result.intents,
            "quoted": result.quoted,
            "rejected": result.rejected,
            "hard_stops": result.hard_stops,
            "committed_usd": result.committed_usd,
        }

    # -- the loop ---------------------------------------------------------

    def run_forever(self) -> None:
        """Cycle, sleep, cycle, until :meth:`stop` is called."""
        self.start()
        while self._running:
            try:
                self.run_once()
            except (CLOBError, ExecutionError) as exc:
                LOGGER.error("cycle failed: %s", exc)
                self.journal.append("error", kind_of_error=type(exc).__name__, error=str(exc))
            except Exception as exc:  # noqa: BLE001 - the service must survive
                LOGGER.exception("cycle failed: %s", exc)
                self.journal.append("error", kind_of_error=type(exc).__name__, error=str(exc))
            self._sleep(self.runner_config.interval_seconds)

    def _sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(seconds, 0.0)
        while self._running and time.monotonic() < deadline:
            time.sleep(min(0.2, max(deadline - time.monotonic(), 0.0)))

    # -- shutdown ---------------------------------------------------------

    def shutdown(self) -> None:
        """Stop the service in the order the venue requires.

        Cancel all orders first. The venue cancels every open order on the
        API key when the heartbeat lapses, so the heartbeat is stopped only
        after our own cancellations have gone out. The client closes last.
        """
        self._cancel_all()
        self._stop_heartbeat()
        self._close_executor()

    def _cancel_all(self) -> None:
        try:
            self.executor.cancel_all()
        except ExecutionError as exc:
            LOGGER.warning("cancel-all failed: %s", exc)
        self._resting.clear()

    def _stop_heartbeat(self) -> None:
        if self.heartbeat is None:
            return
        try:
            self.heartbeat.stop()
        except Exception as exc:  # noqa: BLE001 - shutdown must finish
            LOGGER.warning("heartbeat stop failed: %s", exc)
        self.heartbeat = None

    def _close_executor(self) -> None:
        try:
            self.executor.close()
        except Exception as exc:  # noqa: BLE001 - shutdown must finish
            LOGGER.warning("client close failed: %s", exc)
