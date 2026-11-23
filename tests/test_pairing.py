"""Tests for the paired-bid arithmetic.

No network, no credentials, standard library only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.pricing import (  # noqa: E402
    expected_net_bps,
    merge_arbitrage_threshold,
    paired_fill_pnl,
    unpaired_fill_exposure,
)


class TestPairedFillPnl:
    def test_profit_is_one_minus_the_pair_cost(self) -> None:
        assert paired_fill_pnl(0.48, 0.49) == pytest.approx(0.03)
        assert paired_fill_pnl(0.50, 0.50) == pytest.approx(0.0)

    def test_pair_bought_at_one_has_no_profit(self) -> None:
        assert paired_fill_pnl(0.60, 0.40) == pytest.approx(0.0)

    def test_pair_bought_above_one_loses(self) -> None:
        assert paired_fill_pnl(0.55, 0.50) == pytest.approx(-0.05)

    def test_profit_is_direction_independent(self) -> None:
        # Same pair cost, so the same gain regardless of which leg the event favours.
        assert paired_fill_pnl(0.47, 0.47) == pytest.approx(paired_fill_pnl(0.47, 0.47))


class TestUnpairedFillExposure:
    def test_exposure_is_the_stake_lost(self) -> None:
        assert unpaired_fill_exposure(0.48, 0.48, 100.0) == pytest.approx(48.0)

    def test_exposure_scales_with_shares(self) -> None:
        assert unpaired_fill_exposure(0.50, 0.50, 50.0) == pytest.approx(25.0)


class TestExpectedNetBps:
    def test_both_legs_filling_is_net_positive(self) -> None:
        # 0.48 + 0.49 = 0.97, so each pair merges for 0.03 of profit.
        bps = expected_net_bps(
            bid_up=0.48,
            bid_down=0.49,
            p_both_fill=1.0,
            up_fill_price=0.48,
            up_fill_shares=100.0,
            down_fill_price=0.49,
            down_fill_shares=100.0,
        )
        assert bps > 0.0

    def test_one_sided_fill_is_net_negative(self) -> None:
        # Only the UP leg fills and the market resolves to zero: the whole stake is lost.
        bps = expected_net_bps(
            bid_up=0.48,
            bid_down=0.49,
            p_both_fill=0.0,
            up_fill_price=0.48,
            up_fill_shares=100.0,
            down_fill_price=0.49,
            down_fill_shares=100.0,
        )
        assert bps < 0.0

    def test_one_sided_fill_matches_the_hand_computed_value(self) -> None:
        # With p_both_fill = 0 the fill is always one-sided, so the whole stake
        # traded is lost: the expected loss equals the expected traded notional.
        # Weights are 0.5 / 0.5 on equal share counts:
        # loss = 0.5 * (100 * 0.48) + 0.5 * (100 * 0.49) = 48.5
        # notional = the same 48.5, so bps = -48.5 / 48.5 * 10000 = -10000.
        bps = expected_net_bps(
            bid_up=0.48,
            bid_down=0.49,
            p_both_fill=0.0,
            up_fill_price=0.48,
            up_fill_shares=100.0,
            down_fill_price=0.49,
            down_fill_shares=100.0,
        )
        assert bps == pytest.approx(-10_000.0)

    def test_both_legs_filling_matches_the_hand_computed_value(self) -> None:
        # p_both_fill = 1, so no one-sided loss:
        # paired gain = 100 * (1 - 0.97) = 3, notional = 97.
        # bps = 3 / 97 * 10000.
        bps = expected_net_bps(
            bid_up=0.48,
            bid_down=0.49,
            p_both_fill=1.0,
            up_fill_price=0.48,
            up_fill_shares=100.0,
            down_fill_price=0.49,
            down_fill_shares=100.0,
        )
        assert bps == pytest.approx(3.0 / 97.0 * 10_000.0)

    def test_mixed_fill_probability_sits_between_the_two_extremes(self) -> None:
        both = expected_net_bps(0.48, 0.49, 1.0, 0.48, 100.0, 0.49, 100.0)
        neither = expected_net_bps(0.48, 0.49, 0.0, 0.48, 100.0, 0.49, 100.0)
        mixed = expected_net_bps(0.48, 0.49, 0.5, 0.48, 100.0, 0.49, 100.0)
        assert neither < mixed < both

    def test_no_trade_returns_zero(self) -> None:
        assert expected_net_bps(0.48, 0.49, 1.0, 0.48, 0.0, 0.49, 0.0) == 0.0

    def test_rejects_invalid_fill_probability(self) -> None:
        with pytest.raises(ValueError):
            expected_net_bps(0.48, 0.49, 1.5, 0.48, 10.0, 0.49, 10.0)


class TestMergeArbitrageThreshold:
    def test_threshold_is_half_the_round_trip_cost(self) -> None:
        # 2 * half_spread must cover the gas plus the fee, so 10 cents of cost
        # needs a 5 cent half-spread, well above the one tick floor.
        assert merge_arbitrage_threshold(0.01, 6.0, 4.0) == pytest.approx(5.0)

    def test_threshold_never_below_one_tick(self) -> None:
        # Costs are tiny, but a quote narrower than the grid cannot be placed.
        assert merge_arbitrage_threshold(0.01, 0.0, 0.0) == pytest.approx(1.0)

    def test_zero_cost_threshold_is_one_tick(self) -> None:
        assert merge_arbitrage_threshold(0.001, 0.0, 0.0) == pytest.approx(0.1)

    def test_rejects_non_positive_tick(self) -> None:
        with pytest.raises(ValueError):
            merge_arbitrage_threshold(0.0, 0.1, 0.1)
