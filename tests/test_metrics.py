"""Tests for the monitor metric computations.

No network, no credentials, standard library only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.monitor import metrics  # noqa: E402


def _fill(notional: float, pnl: float, ts: float | None = None) -> dict:
    fill = {"notional": notional, "pnl": pnl}
    if ts is not None:
        fill["ts"] = ts
    return fill


class TestRealizedBps:
    def test_net_capture_in_bps_of_notional(self) -> None:
        fills = [_fill(100.0, 0.05), _fill(300.0, -0.01)]
        # net pnl 0.04 on 400 notional is 0.01 bps
        assert metrics.realized_bps(fills, {}) == pytest.approx(1.0)

    def test_negative_capture_is_negative(self) -> None:
        fills = [_fill(100.0, -0.055)]
        assert metrics.realized_bps(fills, {}) == pytest.approx(-5.5)

    def test_falls_back_to_the_journal_totals(self) -> None:
        journal = {"total_notional": 1000.0, "total_pnl": 0.5, "fees": 0.0}
        assert metrics.realized_bps([], journal) == pytest.approx(5.0)

    def test_journal_fees_are_subtracted(self) -> None:
        journal = {"total_notional": 1000.0, "total_pnl": 0.5, "fees": 0.2}
        assert metrics.realized_bps([], journal) == pytest.approx(3.0)

    def test_no_data_is_zero(self) -> None:
        assert metrics.realized_bps([], {}) == 0.0


class TestRollingNetBps:
    def test_mean_over_the_window(self) -> None:
        fills = [_fill(100.0, 0.01), _fill(100.0, -0.03)]
        # +1 bps and -3 bps, mean -1 bp
        assert metrics.rolling_net_bps(fills) == pytest.approx(-1.0)

    def test_uses_only_the_last_window(self) -> None:
        fills = [_fill(100.0, 0.01)] * 100 + [_fill(100.0, -0.03)] * 100
        assert metrics.rolling_net_bps(fills, window=100) == pytest.approx(-3.0)

    def test_empty_history_is_zero_not_a_loss(self) -> None:
        assert metrics.rolling_net_bps([]) == 0.0

    def test_rejects_a_non_positive_window(self) -> None:
        with pytest.raises(ValueError):
            metrics.rolling_net_bps([_fill(1.0, 0.0)], window=0)


class TestWinRate:
    def test_counts_positive_fills(self) -> None:
        fills = [_fill(1.0, 0.1), _fill(1.0, -0.1), _fill(1.0, 0.2)]
        assert metrics.win_rate(fills) == pytest.approx(2 / 3)

    def test_empty_history(self) -> None:
        assert metrics.win_rate([]) == 0.0


class TestInventoryExposure:
    def test_one_sided_position_risks_that_leg(self) -> None:
        exposure = metrics.inventory_exposure(100.0, 0.0, 0.60, 0.40)
        assert exposure == pytest.approx(60.0)

    def test_paired_position_risks_the_larger_leg(self) -> None:
        exposure = metrics.inventory_exposure(100.0, 40.0, 0.60, 0.40)
        assert exposure == pytest.approx(60.0)

    def test_flat_position_has_no_exposure(self) -> None:
        assert metrics.inventory_exposure(0.0, 0.0, 0.60, 0.40) == 0.0


class TestPairCoverage:
    def test_complete_set_is_fully_covered(self) -> None:
        assert metrics.pair_coverage(100.0, 100.0) == pytest.approx(1.0)

    def test_one_sided_position_has_no_coverage(self) -> None:
        assert metrics.pair_coverage(100.0, 0.0) == 0.0

    def test_half_paired_position(self) -> None:
        assert metrics.pair_coverage(100.0, 50.0) == pytest.approx(2 / 3)

    def test_empty_position(self) -> None:
        assert metrics.pair_coverage(0.0, 0.0) == 0.0


class TestRewardEstimate:
    def test_proportional_to_the_score_share(self) -> None:
        estimate = metrics.reward_estimate(50.0, 4.5, 10.0, 25.0, 100.0)
        assert estimate == pytest.approx(2.5)

    def test_full_share_is_the_whole_daily_rate(self) -> None:
        estimate = metrics.reward_estimate(50.0, 4.5, 10.0, 100.0, 100.0)
        assert estimate == pytest.approx(10.0)

    def test_share_is_capped_at_the_daily_rate(self) -> None:
        estimate = metrics.reward_estimate(50.0, 4.5, 10.0, 200.0, 100.0)
        assert estimate == pytest.approx(10.0)

    def test_no_market_score_means_no_reward(self) -> None:
        assert metrics.reward_estimate(50.0, 4.5, 10.0, 5.0, 0.0) == 0.0

    def test_order_below_the_minimum_size_scores_nothing(self) -> None:
        estimate = metrics.reward_estimate(
            50.0, 4.5, 10.0, 25.0, 100.0, quote_size=10.0
        )
        assert estimate == 0.0

    def test_quote_outside_the_spread_band_scores_nothing(self) -> None:
        estimate = metrics.reward_estimate(
            50.0, 4.5, 10.0, 25.0, 100.0, quote_size=50.0, quote_spread_cents=6.0
        )
        assert estimate == 0.0
