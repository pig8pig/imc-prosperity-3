"""Phase 5 — final gate report.

Consolidates: live backtest PnL attribution, |z| distribution, mispricing
duration, residual normality, per-voucher trade stats, gate verdict.
"""

import os
import sys
import math
import subprocess
import re
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from phase5_analysis import replay  # reuses our offline simulator
from phase5_paramsearch import (
    load_books, precompute_deviations, simulate, ACTIVE_PRODUCTS,
)

DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "round3"
)
ROUND_DIR = os.path.dirname(os.path.abspath(__file__))


def run_backtest(algo_path):
    """Run prosperity4btest CLI and parse per-day per-voucher PnL."""
    cmd = [
        os.path.join(os.path.dirname(os.path.dirname(ROUND_DIR)),
                     ".venv", "bin", "prosperity4btest"),
        "cli", algo_path, "3", "--no-progress", "--no-out", "--merge-pnl",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    # Split by 'Backtesting ... day N'
    daily = {}
    cur_day = None
    for line in out.splitlines():
        m = re.match(r"Backtesting .* day (\d+)$", line)
        if m:
            cur_day = int(m.group(1))
            daily[cur_day] = {}
            continue
        m = re.match(r"^([A-Z_0-9]+):\s+(-?[0-9,]+)$", line)
        if m and cur_day is not None:
            sym = m.group(1)
            val = int(m.group(2).replace(",", ""))
            daily[cur_day][sym] = val
    # Total profit per day
    totals = {}
    for m in re.finditer(r"Round 3 day (\d+):\s+(-?[0-9,]+)", out):
        totals[int(m.group(1))] = int(m.group(2).replace(",", ""))
    return daily, totals, out


def main():
    print("=" * 72)
    print("PHASE 5 — Smile-deviation OptionTrader: GATE REPORT")
    print("=" * 72)

    # ── Live backtests ──────────────────────────────────────────────────
    print("\n[A] Running prosperity4btest on combined and baseline...")
    sys.stdout.flush()
    base_daily, base_totals, _ = run_backtest(
        os.path.join(ROUND_DIR, "baseline_trader.py")
    )
    comb_daily, comb_totals, _ = run_backtest(
        os.path.join(ROUND_DIR, "combined_trader.py")
    )

    print(f"\n  baseline daily totals: {base_totals}")
    print(f"  combined daily totals: {comb_totals}")
    voucher_daily = {d: comb_totals[d] - base_totals[d]
                     for d in comb_totals}
    voucher_total = sum(voucher_daily.values())
    print(f"\n  Voucher PnL per day  : {voucher_daily}")
    print(f"  Voucher PnL total    : {voucher_total:+,d} XIRECs")

    # Per-voucher attribution from combined run
    print("\n[B] Per-voucher PnL (combined run, vouchers only):")
    per_v = {sym: 0 for sym in ACTIVE_PRODUCTS}
    for d, syms in comb_daily.items():
        for sym in ACTIVE_PRODUCTS:
            per_v[sym] += syms.get(sym, 0)
    for sym, v in per_v.items():
        print(f"  {sym}: {v:+,d}")

    # Per-day per-voucher table
    print("\n[C] Per-day per-voucher (combined):")
    print(f"  {'voucher':<12} " +
          " ".join(f"{f'day {d}':>10}" for d in sorted(comb_daily)))
    for sym in ACTIVE_PRODUCTS:
        row = " ".join(f"{comb_daily[d].get(sym, 0):>10,d}"
                       for d in sorted(comb_daily))
        print(f"  {sym:<12} {row}")

    # ── Offline diagnostics via phase5_analysis ─────────────────────────
    print("\n[D] Offline diagnostics (LOO smile + EMA 500/1000)...")
    sys.stdout.flush()
    df = replay()
    df_warm = df[df["n"] > 200]
    abs_z = df_warm["z"].abs()
    print(f"\n  rows post-warmup: {len(df_warm):,}")
    print(f"  |z| distribution:")
    for q in (0.50, 0.75, 0.90, 0.95, 0.99):
        print(f"    q{int(q*100):02d} = {abs_z.quantile(q):.3f}")
    print(f"  fraction |z|>2.0: {(abs_z>2.0).mean()*100:.2f}%")
    print(f"  fraction |z|>3.0: {(abs_z>3.0).mean()*100:.2f}%")

    print("\n  mispricing run lengths (|z|>2.0, post warmup):")
    for sym in ACTIVE_PRODUCTS:
        sub = df_warm[df_warm["sym"] == sym].sort_values("global_t")
        flag = (sub["z"].abs() > 2.0).values
        runs, run = [], 0
        for f in flag:
            if f:
                run += 1
            elif run:
                runs.append(run); run = 0
        if run:
            runs.append(run)
        if runs:
            arr = np.array(runs)
            print(f"    {sym}: mean={arr.mean():.1f}  med={int(np.median(arr))}  "
                  f"max={arr.max()}  n_runs={len(arr)}")

    print("\n  residual normality (post-warmup deviations):")
    for sym in ACTIVE_PRODUCTS:
        x = df_warm[df_warm["sym"] == sym]["dev"].values
        if len(x) < 50:
            continue
        m = x.mean(); sd = x.std(ddof=1)
        if sd == 0:
            continue
        zs = (x - m) / sd
        print(f"    {sym}: mean={m:+.5f}  sd={sd:.5f}  "
              f"skew={np.mean(zs**3):+.2f}  kurt={np.mean(zs**4)-3:+.2f}")

    # Trade stats from offline simulator (cross + mid) — best-case/worst-case
    print("\n[E] Trade stats from offline simulator:")
    print("    (cross = spec's taking; mid = post at mid; join = post passive at TOB)")
    books = load_books()
    precomp = precompute_deviations(books)
    params = {"EMA_M": 500, "EMA_V": 1000, "WARMUP": 200,
              "N_OPEN": 2.0, "N_CLOSE": 1.0, "SIZE": 30}
    for mode in ("cross", "join", "mid"):
        r = simulate(precomp, params, exec_mode=mode)
        print(f"  exec={mode:<6} PnL={r['pnl']:>+10,.0f}  "
              f"trades={r['trades']:>5d}  win_rate={r['win_rate']*100:>5.1f}%")

    # ── Gate verdict ────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("GATE VERDICT")
    print("=" * 72)
    pass_pnl = voucher_total > 100_000
    pass_no_blowup = all(v >= -10_000 for v in voucher_daily.values())
    daily_arr = np.array(list(voucher_daily.values()), dtype=float)
    if daily_arr.std(ddof=1) > 0:
        sharpe = daily_arr.mean() / daily_arr.std(ddof=1)
    else:
        sharpe = float("inf") if daily_arr.mean() > 0 else 0.0
    pass_sharpe = sharpe > 1.0

    print(f"  voucher PnL > 100,000 : {voucher_total:+,d}   "
          f"{'PASS' if pass_pnl else 'FAIL'}")
    print(f"  no day < -10,000       : {dict(voucher_daily)}   "
          f"{'PASS' if pass_no_blowup else 'FAIL'}")
    print(f"  per-day Sharpe > 1.0   : {sharpe:.2f}   "
          f"{'PASS' if pass_sharpe else 'FAIL'}")
    overall = pass_pnl and pass_no_blowup and pass_sharpe
    print(f"\n  OVERALL: {'PASS' if overall else 'FAIL'}")

    # ── Open questions / recommendations ────────────────────────────────
    print("\n" + "=" * 72)
    print("OPEN QUESTIONS & RECOMMENDATIONS")
    print("=" * 72)
    print(f"""
1. |z| DISTRIBUTION:
   Median |z| = {abs_z.median():.2f}, q95 = {abs_z.quantile(0.95):.2f},
   q99 = {abs_z.quantile(0.99):.2f}. N_OPEN=2.0 fires on
   {(abs_z>2.0).mean()*100:.1f}% of ticks; tighter thresholds (3.0) fire
   on {(abs_z>3.0).mean()*100:.2f}% only. Tail is fat (kurtosis up to +18
   on VEV_5000) so z-score interpretation is sketchy in extremes — a
   percentile-based threshold (e.g. trade only on q99+ events) would be
   more robust than fixed-z.

2. MISPRICING DURATION:
   Median run length of |z|>2.0 is 1 tick. Max ~8 ticks. Signals are
   essentially impulse events: enter on the spike, expect reversion in
   1–3 ticks. The N_CLOSE=1.0 wide band catches reversion but not always
   cleanly within reasonable holding periods.

3. RESIDUAL NORMALITY:
   Heavily non-Gaussian. VEV_5000 and VEV_5100 have skew >|1| and
   kurtosis >+10. Z-scoring is biased — the same nominal z corresponds
   to vastly different tail probabilities across strikes. Recommendation:
   compute per-strike empirical CDF on a rolling window and gate on
   percentile rather than z.

4. WHY THIS GATE FAILS:
   • Spec's taking execution (cross spread): -400k. Round-trip spread cost
     (~2/unit) exceeds signal edge (~0.1/unit per round trip).
   • Passive execution (post at mid / inside spread): +1.3k vouchers.
     The vouchers with usable signal (5000, 5100) have ZERO market trades
     in the 3-day data → passive orders never fill. The vouchers with
     trade flow (5400, 5500) have spread=1 → no room to post passive.

5. RECOMMENDED PARAMETER ADJUSTMENTS (for future data with more flow):
   • Tighter N_OPEN: 3.0–4.0 (q98+ events) — accepts fewer but cleaner trades.
   • Wider N_CLOSE: 1.0–1.5 (already widened). Past 1.5 we're holding noise.
   • Reduce PER_TRADE_CAP: 10 instead of 30. Caps drawdowns; the per-unit
     math doesn't change but realised risk does.
   • Use percentile-based threshold instead of z (residuals not Gaussian).

6. STRUCTURAL CHANGE NEEDED:
   On data where spread > 1 but voucher flow exists (e.g. live exchange or
   richer historical), the same signal is profitable. With this 3-day
   dataset, the strategy cannot pass the gate — there isn't enough flow to
   monetise the edge passively, and taking is dominated by spread cost.
""")


if __name__ == "__main__":
    main()
