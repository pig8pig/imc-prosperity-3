"""Phase 5 — offline diagnostics for the smile-deviation signal.

Replays the smile fit + EMA z-score over 3 days of mid prices WITHOUT
trading, then prints:
 - distribution of |z|
 - how long signals (|z|>N_OPEN) persist
 - normality of fit residuals
"""

import os
import sys
import math
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bs_pricer import implied_vol

DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "round3"
)
ACTIVE_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
ACTIVE_PRODUCTS = [f"VEV_{k}" for k in ACTIVE_STRIKES]
EMA_MEAN_WINDOW = 500
EMA_VAR_WINDOW = 1000
USE_LOO = True  # leave-one-out smile fit
START_TTE_DAYS = 5
TICKS_PER_DAY = 10_000
TIMESTAMP_STEP = 100
N_OPEN = 2.0


def tte_years(global_t):
    tick = global_t / TIMESTAMP_STEP
    return (START_TTE_DAYS * TICKS_PER_DAY - tick) / (TICKS_PER_DAY * 365)


def load_wide():
    frames = []
    for d in (0, 1, 2):
        df = pd.read_csv(os.path.join(DATA_DIR, f"prices_round_3_day_{d}.csv"),
                         sep=";")
        df = df[df["product"].isin(ACTIVE_PRODUCTS + ["VELVETFRUIT_EXTRACT"])]
        df["day"] = d
        df["global_t"] = df["day"] * 1_000_000 + df["timestamp"]
        frames.append(df)
    full = pd.concat(frames, ignore_index=True)
    wide = full.pivot_table(
        index=["day", "timestamp", "global_t"], columns="product",
        values="mid_price", aggfunc="first",
    ).reset_index().sort_values("global_t").reset_index(drop=True)
    return wide


def replay():
    wide = load_wide()
    ttes = wide["global_t"].apply(tte_years).values

    alpha_m = 2.0 / (EMA_MEAN_WINDOW + 1)
    alpha_v = 2.0 / (EMA_VAR_WINDOW + 1)

    state = {sym: {"ema_dev": 0.0, "ema_var": 0.0, "n": 0}
             for sym in ACTIVE_PRODUCTS}

    rows = []
    for i in range(len(wide)):
        T = ttes[i]
        if T <= 0:
            continue
        S = wide["VELVETFRUIT_EXTRACT"].values[i]
        if not np.isfinite(S):
            continue
        ms, ivs, syms_for_fit, mids = [], [], [], []
        for sym, K in zip(ACTIVE_PRODUCTS, ACTIVE_STRIKES):
            mid = wide[sym].values[i]
            if not np.isfinite(mid):
                continue
            iv = implied_vol(float(mid), float(S), float(K), float(T))
            if math.isnan(iv):
                continue
            ms.append(math.log(K / S) / math.sqrt(T))
            ivs.append(iv)
            syms_for_fit.append(sym)
            mids.append((K, mid, iv))
        if len(ms) < 4:
            continue
        ms_arr = np.array(ms); ivs_arr = np.array(ivs)
        coeffs_full = np.polyfit(ms_arr, ivs_arr, 2)
        for j, sym in enumerate(syms_for_fit):
            if USE_LOO and len(ms) >= 5:
                mask = np.ones(len(ms), dtype=bool); mask[j] = False
                cf = np.polyfit(ms_arr[mask], ivs_arr[mask], 2)
            else:
                cf = coeffs_full
            iv_fit = cf[0] * ms[j] ** 2 + cf[1] * ms[j] + cf[2]
            dev = ivs[j] - iv_fit
            st = state[sym]
            diff = dev - st["ema_dev"]
            st["ema_dev"] = st["ema_dev"] + alpha_m * diff
            st["ema_var"] = (1.0 - alpha_v) * (st["ema_var"]
                                               + alpha_v * diff * diff)
            sd = math.sqrt(max(st["ema_var"], 0.0))
            st["n"] += 1
            z = (dev - st["ema_dev"]) / max(sd, 0.001)
            z = max(-10.0, min(10.0, z))
            rows.append({
                "global_t": int(wide["global_t"].values[i]),
                "day": int(wide["day"].values[i]),
                "sym": sym, "iv": ivs[j], "iv_fit": iv_fit,
                "dev": dev, "ema": st["ema_dev"], "sd": sd,
                "z": z, "n": st["n"],
            })
    return pd.DataFrame(rows)


def main():
    print("=" * 70)
    print("PHASE 5 — offline smile-deviation diagnostics")
    print("=" * 70)

    df = replay()
    print(f"\n  total signal rows: {len(df):,}")
    df_warm = df[df["n"] > 100]
    print(f"  rows after warmup (n>100): {len(df_warm):,}")
    print(f"  per-sym counts:\n{df_warm['sym'].value_counts()}")

    # |z| distribution
    print("\n[1] |z| distribution after warmup")
    abs_z = df_warm["z"].abs()
    qs = [0.50, 0.75, 0.90, 0.95, 0.99]
    print(f"  mean = {abs_z.mean():.3f}, std = {abs_z.std():.3f}")
    for q in qs:
        print(f"  q{int(q*100):02d} = {abs_z.quantile(q):.3f}")
    print(f"  fraction |z| > {N_OPEN}: "
          f"{(abs_z > N_OPEN).mean()*100:.2f}%")
    print(f"  fraction |z| > 2.5    : {(abs_z > 2.5).mean()*100:.2f}%")
    print(f"  fraction |z| > 3.0    : {(abs_z > 3.0).mean()*100:.2f}%")

    # Persistence: avg run length of |z|>N_OPEN per voucher
    print("\n[2] How long do |z|>N_OPEN signals persist (in ticks)?")
    for sym in ACTIVE_PRODUCTS:
        sub = df_warm[df_warm["sym"] == sym].sort_values("global_t")
        flag = (sub["z"].abs() > N_OPEN).values
        # run-length encode
        runs = []
        run = 0
        for f in flag:
            if f:
                run += 1
            else:
                if run > 0:
                    runs.append(run)
                run = 0
        if run > 0:
            runs.append(run)
        if runs:
            arr = np.array(runs)
            print(f"  {sym}: n_runs={len(arr):>4}  "
                  f"mean={arr.mean():.1f}  med={np.median(arr):.0f}  "
                  f"max={arr.max():>4}")

    # Sign flips: how often does z change sign? (round-trip frequency)
    print("\n[3] z sign-flip frequency per voucher (mean ticks between flips)")
    for sym in ACTIVE_PRODUCTS:
        sub = df_warm[df_warm["sym"] == sym].sort_values("global_t")
        signs = np.sign(sub["z"].values)
        flips = (signs[1:] * signs[:-1] < 0).sum()
        if flips > 0:
            print(f"  {sym}: flips={flips:>4}, "
                  f"avg ticks/flip={len(sub)/flips:.1f}")

    # Residual normality: skew and kurtosis of dev (per voucher)
    print("\n[4] Smile-fit residual normality per voucher")
    for sym in ACTIVE_PRODUCTS:
        sub = df_warm[df_warm["sym"] == sym]
        x = sub["dev"].values
        if len(x) < 50:
            continue
        m = np.mean(x); sd = np.std(x, ddof=1)
        if sd == 0:
            continue
        z = (x - m) / sd
        skew = np.mean(z ** 3)
        kurt = np.mean(z ** 4) - 3.0
        print(f"  {sym}: n={len(x):>5}  mean={m:+.5f}  std={sd:.5f}  "
              f"skew={skew:+.3f}  excess_kurt={kurt:+.3f}")

    # Mean residual per voucher (is the smile biased?)
    print("\n[5] Per-voucher mean residual (post-warmup) — bias check")
    for sym in ACTIVE_PRODUCTS:
        sub = df_warm[df_warm["sym"] == sym]
        m = sub["dev"].mean(); sd = sub["dev"].std()
        print(f"  {sym}: mean dev = {m:+.5f}, std = {sd:.5f}, "
              f"bias_z = {m / (sd / math.sqrt(len(sub))):+.1f}")

    # Realised PnL of a naive z-trade (entry at |z|>N_OPEN, exit at next sign-flip)
    print("\n[6] Toy backtest: enter at |z|>N_OPEN, exit at sign flip "
          "(no slippage, mid prices)")
    total = 0.0
    by_sym = {}
    for sym in ACTIVE_PRODUCTS:
        sub = df_warm[df_warm["sym"] == sym].sort_values("global_t").reset_index(drop=True)
        pnl = 0.0; pos = 0; entry_iv = None
        for _, r in sub.iterrows():
            z = r["z"]; iv = r["iv"]
            if pos == 0 and abs(z) > N_OPEN:
                pos = -1 if z > 0 else 1     # rich -> short, cheap -> long
                entry_iv = iv
            elif pos != 0 and (z * (-pos) <= 0):  # z crossed back to opposite of entry
                pnl += -pos * (entry_iv - iv)  # short: entry - exit; long: exit - entry
                pos = 0; entry_iv = None
        by_sym[sym] = pnl
        total += pnl
        print(f"  {sym}: vol-point PnL = {pnl:+.4f}")
    print(f"  TOTAL vol-point PnL = {total:+.4f}  "
          f"(positive => signal direction is profitable in vol-space)")


if __name__ == "__main__":
    main()
