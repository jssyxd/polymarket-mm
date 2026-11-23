"""Tests for the binary pricing engine.

No network, no credentials, standard library only.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.pricing import (  # noqa: E402
    FairProbability,
    Inventory,
    black_scholes_digital_prob,
    build_quotes,
    implied_prob_from_book,
    probability_space_vol,
    round_down_to_tick,
    round_up_to_tick,
)


class TestFairProbability:
    def test_carries_the_full_estimate(self) -> None:
        fair = FairProbability(
            prob=0.52,
            sigma_p=0.0009,
            tau_seconds=600.0,
            strike=100.0,
            spot=100.5,
            method="digital",
        )
        assert fair.prob == pytest.approx(0.52)
        assert fair.method == "digital"

    def test_rejects_an_out_of_range_probability(self) -> None:
        with pytest.raises(ValueError):
            FairProbability(
                prob=1.5,
                sigma_p=0.001,
                tau_seconds=60.0,
                strike=100.0,
                spot=100.0,
                method="digital",
            )


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


class TestBlackScholesDigital:
    def test_matches_hand_computed_d2(self) -> None:
        # spot == strike, sigma = 0.01 per sqrt(second), tau = 100 s.
        # d2 = (ln(1) - 0.5 * 0.01^2 * 100) / (0.01 * 10) = -0.05.
        prob, sigma_p = black_scholes_digital_prob(100.0, 100.0, 0.01, 100.0)
        assert prob == pytest.approx(0.4800611941616275, abs=1e-12)
        assert sigma_p == pytest.approx(0.039844391409476404, abs=1e-12)

    def test_d2_formula_is_reproduced_for_an_off_the_money_strike(self) -> None:
        spot, strike, sigma, tau = 100.0, 95.0, 0.02, 300.0
        prob, sigma_p = black_scholes_digital_prob(spot, strike, sigma, tau)
        d2 = (math.log(spot / strike) - 0.5 * sigma**2 * tau) / (sigma * math.sqrt(tau))
        assert prob == pytest.approx(_norm_cdf(d2), abs=1e-15)
        assert sigma_p == pytest.approx(_norm_pdf(d2) / math.sqrt(tau), abs=1e-15)

    def test_probability_increases_with_spot(self) -> None:
        low, _ = black_scholes_digital_prob(99.0, 100.0, 0.01, 60.0)
        high, _ = black_scholes_digital_prob(101.0, 100.0, 0.01, 60.0)
        assert low < high

    def test_degenerate_horizon_is_deterministic(self) -> None:
        assert black_scholes_digital_prob(100.0, 100.0, 0.01, 0.0) == (1.0, 0.0)
        assert black_scholes_digital_prob(99.0, 100.0, 0.01, 0.0) == (0.0, 0.0)

    def test_zero_volatility_is_deterministic(self) -> None:
        assert black_scholes_digital_prob(101.0, 100.0, 0.0, 60.0) == (1.0, 0.0)
        assert black_scholes_digital_prob(99.0, 100.0, 0.0, 60.0) == (0.0, 0.0)

    def test_rejects_non_positive_prices(self) -> None:
        with pytest.raises(ValueError):
            black_scholes_digital_prob(0.0, 100.0, 0.01, 60.0)
        with pytest.raises(ValueError):
            black_scholes_digital_prob(100.0, 0.0, 0.01, 60.0)


class TestImpliedProbFromBook:
    def test_mid_of_top_of_book(self) -> None:
        book = {"bids": [{"price": "0.49", "size": "100"}], "asks": [{"price": "0.51", "size": "80"}]}
        assert implied_prob_from_book(book) == pytest.approx(0.50)

    def test_uses_best_levels_only(self) -> None:
        book = {
            "bids": [{"price": "0.10", "size": "5"}, {"price": "0.48", "size": "5"}],
            "asks": [{"price": "0.90", "size": "5"}, {"price": "0.52", "size": "5"}],
        }
        assert implied_prob_from_book(book) == pytest.approx(0.50)

    def test_empty_book_falls_back_to_a_coin_flip(self) -> None:
        assert implied_prob_from_book({}) == 0.5
        assert implied_prob_from_book({"bids": [], "asks": []}) == 0.5

    def test_one_sided_book_uses_the_available_level(self) -> None:
        assert implied_prob_from_book({"bids": [{"price": "0.42"}], "asks": []}) == pytest.approx(0.42)


class TestProbabilitySpaceVol:
    def test_is_clamped_to_the_documented_band(self) -> None:
        assert 1e-6 <= probability_space_vol(100.0, 100.0, 600.0) <= 0.05

    def test_upper_clamp_binds_on_a_short_horizon(self) -> None:
        # One second to expiry at the money: the density-based vol is far
        # above the band, so it clamps to the 0.05 ceiling.
        assert probability_space_vol(100.0, 100.0, 1.0) == pytest.approx(0.05)

    def test_deep_out_of_the_money_hits_the_lower_clamp(self) -> None:
        assert probability_space_vol(100.0, 50.0, 600.0) == pytest.approx(1e-6)

    def test_vol_falls_as_the_market_moves_away_from_the_strike(self) -> None:
        near = probability_space_vol(100.0, 99.0, 600.0)
        far = probability_space_vol(100.0, 95.0, 600.0)
        assert near > far

    def test_shorter_horizon_gives_larger_per_second_vol(self) -> None:
        short = probability_space_vol(100.0, 100.0, 60.0)
        long = probability_space_vol(100.0, 100.0, 3600.0)
        assert short >= long


class TestTickRounding:
    def test_bid_rounds_down_and_ask_rounds_up(self) -> None:
        assert round_down_to_tick(0.4849, 0.01) == pytest.approx(0.48)
        assert round_up_to_tick(0.4841, 0.01) == pytest.approx(0.49)

    def test_rounding_lands_exactly_on_the_grid(self) -> None:
        for ticks in range(1, 99):
            price = ticks / 100.0
            for probe in (price - 0.004, price + 0.004):
                down = round_down_to_tick(probe, 0.01)
                up = round_up_to_tick(probe, 0.01)
                assert down <= probe + 1e-12
                assert up >= probe - 1e-12
                assert abs(down / 0.01 - round(down / 0.01)) < 1e-9
                assert abs(up / 0.01 - round(up / 0.01)) < 1e-9


class TestBuildQuotes:
    def _quote(self, **overrides):
        params = dict(
            fair_prob=0.52,
            sigma_p=0.0009,
            tau_seconds=600.0,
            tick_size=0.01,
            min_size=5.0,
            inventory=Inventory(up_shares=0.0, down_shares=0.0, max_inventory_per_side=100.0),
        )
        params.update(overrides)
        return build_quotes(**params)

    def test_prices_sit_on_the_tick_grid(self) -> None:
        quote = self._quote()
        for price in (quote.up.price, quote.down.price):
            assert price >= 0.0
            assert abs(price / 0.01 - round(price / 0.01)) < 1e-9

    def test_pair_invariant_holds_across_the_probability_range(self) -> None:
        for cents in range(1, 100):
            for sigma_p in (0.0, 0.0009, 0.05):
                for up_shares in (0.0, 50.0, 100.0):
                    quote = self._quote(
                        fair_prob=cents / 100.0,
                        sigma_p=sigma_p,
                        inventory=Inventory(
                            up_shares=up_shares,
                            down_shares=0.0,
                            max_inventory_per_side=100.0,
                        ),
                    )
                    assert quote.up.price + quote.down.price <= 1.0 - 0.01 + 1e-12

    def test_fair_prob_is_clamped_onto_the_tradable_band(self) -> None:
        quote = self._quote(fair_prob=0.0)
        assert quote.fair_prob == pytest.approx(0.01)
        quote = self._quote(fair_prob=1.0)
        assert quote.fair_prob == pytest.approx(0.99)

    def test_reward_spread_sets_the_half_spread_ceiling(self) -> None:
        quote = self._quote(reward_max_spread_cents=4.5)
        # The venue pays a reward only for orders inside its max spread, so
        # the band caps the half-spread. It never lifts it.
        assert quote.half_spread <= 0.036 + 1e-12
        assert quote.half_spread <= 0.20

    def test_the_quote_stays_inside_the_reward_band(self) -> None:
        quote = self._quote(reward_max_spread_cents=4.5, sigma_p=0.05, tau_seconds=86400.0)
        # A long horizon and a large sigma would widen the spread well past
        # the band without the ceiling.
        assert quote.half_spread <= 0.036 + 1e-12

    def test_explicit_half_spread_cents_sets_the_floor(self) -> None:
        quote = self._quote(half_spread_cents=5.0)
        assert quote.half_spread >= 0.05 - 1e-12

    def test_one_tick_minimum_floor(self) -> None:
        quote = self._quote(half_spread_cents=0.0, reward_max_spread_cents=None)
        assert quote.half_spread >= 0.01 - 1e-12

    def test_inventory_skew_lowers_the_up_bid_and_raises_the_down_bid(self) -> None:
        flat = self._quote(sigma_p=0.05)
        long_up = self._quote(
            sigma_p=0.05,
            inventory=Inventory(up_shares=100.0, down_shares=0.0, max_inventory_per_side=100.0),
        )
        assert long_up.up.price < flat.up.price
        assert long_up.down.price > flat.down.price

    def test_inventory_skew_is_symmetric_under_a_flip(self) -> None:
        flat = self._quote(sigma_p=0.05)
        long_up = self._quote(
            sigma_p=0.05,
            inventory=Inventory(up_shares=100.0, down_shares=0.0, max_inventory_per_side=100.0),
        )
        long_down = self._quote(
            sigma_p=0.05,
            inventory=Inventory(up_shares=0.0, down_shares=100.0, max_inventory_per_side=100.0),
        )
        # Long up lowers the up bid and lifts the down bid; long down does the reverse.
        assert long_up.up.price < flat.up.price < long_down.up.price
        assert long_down.down.price < flat.down.price < long_up.down.price
        # Both skews leave the pair cost unchanged.
        assert long_up.up.price + long_up.down.price == pytest.approx(
            long_down.up.price + long_down.down.price
        )

    def test_size_is_the_reward_size_when_one_is_configured(self) -> None:
        quote = self._quote(min_reward_size=50.0)
        assert quote.up.size == pytest.approx(50.0)
        assert quote.down.size == pytest.approx(50.0)

    def test_size_falls_back_to_min_size(self) -> None:
        quote = self._quote(min_size=7.0)
        assert quote.up.size == pytest.approx(7.0)

    def test_inventory_box_silences_the_breached_leg(self) -> None:
        quote = self._quote(
            inventory=Inventory(up_shares=100.0, down_shares=0.0, max_inventory_per_side=100.0)
        )
        assert quote.up.size == 0.0
        assert quote.down.size > 0.0
        assert "up_leg_at_inventory_box" in quote.reason

    def test_expiry_is_in_the_future(self) -> None:
        quote = self._quote(tau_seconds=600.0)
        assert quote.expires_at > 0.0

    def test_worked_example(self) -> None:
        # fair 0.52, sigma_p 0.0009, tau 600 s, tick 0.01, reward spread 4.5 cents.
        # No explicit half-spread was asked for, so the floor is one tick and
        # the time-and-volatility widening takes it to 1.011 ticks. The band
        # caps it, and does not lift it.
        quote = build_quotes(
            fair_prob=0.52,
            sigma_p=0.0009,
            tau_seconds=600.0,
            tick_size=0.01,
            min_size=5.0,
            inventory=Inventory(up_shares=0.0, down_shares=0.0, max_inventory_per_side=100.0),
            reward_max_spread_cents=4.5,
        )
        assert quote.half_spread == pytest.approx(0.010110227038425243)
        # Bids round down onto the 0.01 grid: 0.50989 becomes 0.50 and
        # 0.46989 becomes 0.46.
        assert quote.up.price == pytest.approx(0.50)
        assert quote.down.price == pytest.approx(0.46)
        assert quote.up.size == pytest.approx(5.0)
        assert quote.down.size == pytest.approx(5.0)
        # The pair is bought for 0.96 and merges back for 1.
        assert quote.up.price + quote.down.price == pytest.approx(0.96)
