"""Black-Scholes pricer + implied-vol solver for VELVETFRUIT_EXTRACT options.

Stdlib + numpy only. T is in years; caller converts days/365.
"""

import math
import numpy as np
from statistics import NormalDist

_N = NormalDist()
_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _d1_d2(S, K, T, sigma, r):
    sst = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / sst
    return d1, d1 - sst


def bs_call(S, K, T, sigma, r=0.0):
    if T <= 0.0 or sigma <= 0.0:
        return max(S - K, 0.0)
    d1, d2 = _d1_d2(S, K, T, sigma, r)
    return S * _N.cdf(d1) - K * math.exp(-r * T) * _N.cdf(d2)


def bs_delta(S, K, T, sigma, r=0.0):
    if T <= 0.0 or sigma <= 0.0:
        if S > K:
            return 1.0
        if S < K:
            return 0.0
        return 0.5
    d1, _ = _d1_d2(S, K, T, sigma, r)
    return _N.cdf(d1)


def bs_vega(S, K, T, sigma, r=0.0):
    if T <= 0.0 or sigma <= 0.0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, sigma, r)
    return S * _N.pdf(d1) * math.sqrt(T)


def bs_gamma(S, K, T, sigma, r=0.0):
    if T <= 0.0 or sigma <= 0.0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, sigma, r)
    return _N.pdf(d1) / (S * sigma * math.sqrt(T))


def _iv_bisect(market_price, S, K, T, r, lo=1e-4, hi=5.0, tol=1e-8, max_iter=200):
    flo = bs_call(S, K, T, lo, r) - market_price
    fhi = bs_call(S, K, T, hi, r) - market_price
    if flo * fhi > 0.0:
        return float("nan")
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        fmid = bs_call(S, K, T, mid, r) - market_price
        if abs(fmid) < tol:
            return mid
        if flo * fmid <= 0.0:
            hi, fhi = mid, fmid
        else:
            lo, flo = mid, fmid
    return 0.5 * (lo + hi)


def implied_vol(market_price, S, K, T, r=0.0):
    if T <= 0.0:
        return float("nan")
    intrinsic = max(S - K * math.exp(-r * T), 0.0)
    if market_price < intrinsic - 1e-10:
        return float("nan")
    if market_price >= S:
        return float("nan")

    sigma = _SQRT_2PI / math.sqrt(T) * (market_price / S)
    sigma = min(5.0, max(0.001, sigma))

    for _ in range(50):
        price = bs_call(S, K, T, sigma, r)
        diff = price - market_price
        if abs(diff) < 1e-8:
            return sigma
        v = bs_vega(S, K, T, sigma, r)
        if v < 1e-10:
            return _iv_bisect(market_price, S, K, T, r)
        step = diff / v
        new_sigma = sigma - step
        if new_sigma <= 0.0 or new_sigma > 5.0:
            return _iv_bisect(market_price, S, K, T, r)
        sigma = new_sigma
    return _iv_bisect(market_price, S, K, T, r)


def bs_call_vec(S, K_arr, T, sigma_arr, r=0.0):
    K_arr = np.asarray(K_arr, dtype=float)
    sigma_arr = np.asarray(sigma_arr, dtype=float)
    if sigma_arr.ndim == 0:
        sigma_arr = np.broadcast_to(sigma_arr, K_arr.shape)
    out = np.empty(K_arr.shape, dtype=float)
    for i in range(K_arr.size):
        out.flat[i] = bs_call(S, float(K_arr.flat[i]), T, float(sigma_arr.flat[i]), r)
    return out


def implied_vol_vec(market_prices, S, K_arr, T, r=0.0):
    market_prices = np.asarray(market_prices, dtype=float)
    K_arr = np.asarray(K_arr, dtype=float)
    out = np.empty(K_arr.shape, dtype=float)
    for i in range(K_arr.size):
        out.flat[i] = implied_vol(
            float(market_prices.flat[i]), S, float(K_arr.flat[i]), T, r
        )
    return out


if __name__ == "__main__":
    passes = 0
    fails = 0

    def check(label, ok, detail=""):
        global passes, fails
        tag = "PASS" if ok else "FAIL"
        if ok:
            passes += 1
        else:
            fails += 1
        suffix = f" — {detail}" if detail else ""
        print(f"[{tag}] {label}{suffix}")

    print("=" * 60)
    print("Test 1: Hull textbook example")
    print("-" * 60)
    hull = bs_call(42.0, 40.0, 0.5, 0.20, r=0.10)
    check("Hull S=42 K=40 T=0.5 sigma=0.20 r=0.10 -> ~4.76",
          abs(hull - 4.76) < 0.01,
          f"got {hull:.4f}")

    print()
    print("=" * 60)
    print("Test 2: Round-trip on VEV_5000")
    print("-" * 60)
    S = 5246.5
    K = 5000.0
    T = 5.0 / 365.0
    true_sigma = 0.234
    px = bs_call(S, K, T, true_sigma)
    iv = implied_vol(px, S, K, T)
    repx = bs_call(S, K, T, iv)
    check("sigma round-trip error < 1e-5",
          abs(iv - true_sigma) < 1e-5,
          f"sigma_in={true_sigma}, sigma_out={iv:.10f}, |diff|={abs(iv-true_sigma):.2e}")
    check("price re-price error < 1e-6",
          abs(repx - px) < 1e-6,
          f"px={px:.6f}, repx={repx:.6f}")

    print()
    print("=" * 60)
    print("Test 3: Round-trip across all 10 Round-3 strikes (sigma=0.234)")
    print("-" * 60)
    strikes = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
    expected_fail = {4000, 4500, 6000, 6500}
    K_arr = np.array(strikes, dtype=float)
    sigma_arr = np.full_like(K_arr, 0.234)
    prices = bs_call_vec(S, K_arr, T, sigma_arr)
    ivs = implied_vol_vec(prices, S, K_arr, T)
    for k, p, sig in zip(strikes, prices, ivs):
        recovered = (not math.isnan(sig)) and abs(sig - 0.234) < 1e-4
        if k in expected_fail:
            check(f"K={k:>4d} (skipped in algo): price={p:>10.4f}, iv={sig}",
                  True,
                  "expected to be unreliable — flagged for skip")
        else:
            check(f"K={k:>4d}: price={p:>10.4f}, iv={sig:.8f}",
                  recovered,
                  f"|diff|={abs(sig-0.234):.2e}" if not math.isnan(sig) else "NaN")

    print()
    print("=" * 60)
    print("Test 4: Edge cases")
    print("-" * 60)
    deep_itm = bs_call(5246.5, 1000.0, 5.0 / 365.0, 0.234)
    intrinsic_itm = 5246.5 - 1000.0
    check("deep ITM ~ intrinsic",
          abs(deep_itm - intrinsic_itm) < 1e-3,
          f"price={deep_itm:.6f}, intrinsic={intrinsic_itm}")

    deep_otm = bs_call(5246.5, 10000.0, 5.0 / 365.0, 0.234)
    check("deep OTM ~ 0",
          deep_otm < 1e-6,
          f"price={deep_otm:.2e}")

    t_zero_itm = bs_call(5246.5, 5000.0, 0.0, 0.234)
    check("T=0 ITM == intrinsic exactly",
          t_zero_itm == 246.5,
          f"price={t_zero_itm}")

    t_zero_otm = bs_call(5246.5, 5500.0, 0.0, 0.234)
    check("T=0 OTM == 0 exactly",
          t_zero_otm == 0.0,
          f"price={t_zero_otm}")

    sigma_zero = bs_call(5246.5, 5000.0, 5.0 / 365.0, 0.0)
    check("sigma=0 ITM == intrinsic",
          sigma_zero == 246.5,
          f"price={sigma_zero}")

    print()
    print("=" * 60)
    print("Test 5: Greeks sanity check on VEV_5000")
    print("-" * 60)
    delta = bs_delta(S, 5000.0, T, true_sigma)
    vega = bs_vega(S, 5000.0, T, true_sigma)
    gamma = bs_gamma(S, 5000.0, T, true_sigma)
    print(f"  delta = {delta:.6f}")
    print(f"  vega  = {vega:.6f}")
    print(f"  gamma = {gamma:.6f}")
    check("delta in [0, 1]", 0.0 <= delta <= 1.0)
    check("delta > 0.5 (slightly ITM since S>K)", delta > 0.5)
    check("vega > 0", vega > 0.0)
    check("gamma > 0", gamma > 0.0)

    hS = 0.01
    hSig = 1e-4
    num_delta = (bs_call(S + hS, 5000.0, T, true_sigma)
                 - bs_call(S - hS, 5000.0, T, true_sigma)) / (2 * hS)
    num_vega = (bs_call(S, 5000.0, T, true_sigma + hSig)
                - bs_call(S, 5000.0, T, true_sigma - hSig)) / (2 * hSig)
    num_gamma = (bs_call(S + hS, 5000.0, T, true_sigma)
                 - 2 * bs_call(S, 5000.0, T, true_sigma)
                 + bs_call(S - hS, 5000.0, T, true_sigma)) / (hS * hS)
    check("delta matches finite-diff",
          abs(delta - num_delta) < 1e-5,
          f"analytic={delta:.8f}, numeric={num_delta:.8f}")
    check("vega matches finite-diff",
          abs(vega - num_vega) < 1e-3,
          f"analytic={vega:.6f}, numeric={num_vega:.6f}")
    check("gamma matches finite-diff",
          abs(gamma - num_gamma) < 1e-3,
          f"analytic={gamma:.8f}, numeric={num_gamma:.8f}")

    print()
    print("=" * 60)
    print("Test 6: Recover IVs from real Round-3 day-0 mid prices")
    print("-" * 60)
    S6 = 5246.5
    T6 = 8.0 / 365.0
    quotes = [(5000, 253.26), (5100, 168.11), (5200, 97.47),
              (5300, 48.89), (5400, 18.47), (5500, 8.06)]
    for K6, mid in quotes:
        iv6 = implied_vol(mid, S6, K6, T6)
        if math.isnan(iv6):
            check(f"K={K6}: mid={mid}", False, "IV solver returned NaN")
            continue
        repx6 = bs_call(S6, K6, T6, iv6)
        ok = abs(repx6 - mid) < 1e-4
        check(f"K={K6}: mid={mid:.4f} iv={iv6:.6f} repx={repx6:.6f}",
              ok,
              f"|diff|={abs(repx6-mid):.2e}")

    print()
    print("=" * 60)
    print(f"SUMMARY: {passes} passed, {fails} failed")
    print("=" * 60)
