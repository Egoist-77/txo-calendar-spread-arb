# tests/test_iv_engine.py
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from calendar_spread_arb.iv_engine import bs_price, bs_vega, calc_iv_newton


class TestBsPrice:
    def test_call_atm_positive(self):
        price = bs_price(sigma=0.20, S=17000, K=17000, T=30/365, r=0.02, cp='C')
        assert price > 0

    def test_put_atm_positive(self):
        price = bs_price(sigma=0.20, S=17000, K=17000, T=30/365, r=0.02, cp='P')
        assert price > 0

    def test_put_call_parity(self):
        import math
        S, K, T, r, sigma = 17000, 17000, 30/365, 0.02, 0.20
        call = bs_price(sigma, S, K, T, r, 'C')
        put  = bs_price(sigma, S, K, T, r, 'P')
        parity = S - K * math.exp(-r * T)
        assert abs((call - put) - parity) < 0.01

    def test_zero_time_call_intrinsic(self):
        price = bs_price(sigma=0.20, S=17100, K=17000, T=0, r=0.02, cp='C')
        assert abs(price - 100) < 0.01

    def test_known_value(self):
        price = bs_price(sigma=0.20, S=17000, K=17000, T=30/365, r=0.02, cp='C')
        assert 250 < price < 500


class TestBsVega:
    def test_vega_positive_atm(self):
        vega = bs_vega(sigma=0.20, S=17000, K=17000, T=30/365, r=0.02)
        assert vega > 0

    def test_vega_zero_at_expiry(self):
        vega = bs_vega(sigma=0.20, S=17000, K=17000, T=0, r=0.02)
        assert vega == 0.0


class TestCalcIvNewton:
    def test_roundtrip_call(self):
        true_iv = 0.18
        S, K, T, r = 17000, 17000, 30/365, 0.02
        price = bs_price(true_iv, S, K, T, r, 'C')
        recovered_iv = calc_iv_newton(price, S, K, T, r, 'C')
        assert recovered_iv is not None
        assert abs(recovered_iv - true_iv) < 0.001

    def test_roundtrip_put(self):
        true_iv = 0.22
        S, K, T, r = 17000, 17200, 30/365, 0.02
        price = bs_price(true_iv, S, K, T, r, 'P')
        recovered_iv = calc_iv_newton(price, S, K, T, r, 'P')
        assert recovered_iv is not None
        assert abs(recovered_iv - true_iv) < 0.001

    def test_returns_none_for_zero_price(self):
        result = calc_iv_newton(0.0, S=17000, K=20000, T=1/365, r=0.02, cp='C')
        assert result is None

    def test_high_vol_roundtrip(self):
        true_iv = 0.50
        S, K, T, r = 17000, 17000, 60/365, 0.02
        price = bs_price(true_iv, S, K, T, r, 'C')
        recovered_iv = calc_iv_newton(price, S, K, T, r, 'C')
        assert recovered_iv is not None
        assert abs(recovered_iv - true_iv) < 0.001
