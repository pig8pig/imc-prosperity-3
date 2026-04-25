"""Realised Vol vs Implied Vol diagnostic for Round-3 VEV vouchers.

Answers: are vouchers structurally over- or under-priced relative to realised?
"""

import os
import sys
import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bs_pricer import implied_vol, bs_call

DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "round3"
)
OUT_PNG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phase3_rv_iv.png")

UNDERLYING = "VELVETFRUIT_EXTRACT"
ACTIVE_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
ACTIVE_PRODUCTS = [f"VEV_{k}" for k in ACTIVE_STRIKES]
TICKS_PER_DAY = 10_000
TICK_STEP = 100
TIMESTAMPS_PER_DAY = TICKS_PER_DAY * TICK_STEP  # 1,000,000
DAYS_PER_YEAR = 365
TICKS_PER_YEAR = TICKS_PER_DAY * DAYS_PER_YEAR  # 3,650,000
ANNUALISATION = math.sqrt(TICKS_PER_YEAR)
START_TTE_DAYS = {0: 8, 1: 7, 2: 6}


def load_all_days():
    frames = []
    for d in (0, 1, 2):
        path = os.path.join(DATA_DIR, f"prices_round_3_day_{d}.csv")
        df = pd.read_csv(path, sep=";")
        df["day"] = d
        frames.append(df)
    full = pd.concat(frames, ignore_index=True)
    keep = [UNDERLYING] + ACTIVE_PRODUCTS
    full = full[full["product"].isin(keep)].copy()
    # Global tick index across the 3 days
    full["global_t"] = full["day"] * TIMESTAMPS_PER_DAY + full["timestamp"]
    return full


def pivot_mids(df):
    wide = df.pivot_table(
        index=["day", "timestamp", "global_t"],
        columns="product",
        values="mid_price",
        aggfunc="first",
    ).reset_index().sort_values("global_t").reset_index(drop=True)
    return wide


def verify_tick_step(wide):
    ts0 = wide.loc[wide["day"] == 0, "timestamp"].sort_values().values
    diffs = np.diff(ts0)
    unique_diffs = np.unique(diffs)
    print(f"  tick-step unique values (day 0): {unique_diffs.tolist()}")
    assert len(unique_diffs) == 1 and unique_diffs[0] == TICK_STEP, (
        f"Expected tick step {TICK_STEP}, got {unique_diffs.tolist()}"
    )
    print(f"  tick step = {TICK_STEP} confirmed.")


def compute_rv(underlying, windows=(100, 1000, 10_000)):
    log_ret = np.log(underlying).diff()
    rvs = {}
    for w in windows:
        # rolling std of per-tick log returns, annualised
        rv = log_ret.rolling(w, min_periods=max(2, w // 4)).std() * ANNUALISATION
        rvs[w] = rv
    return rvs, log_ret


def compute_iv_grid(wide):
    iv_cols = {}
    for k, prod in zip(ACTIVE_STRIKES, ACTIVE_PRODUCTS):
        ivs = np.full(len(wide), np.nan)
        S_arr = wide[UNDERLYING].values
        mid_arr = wide[prod].values
        day_arr = wide["day"].values
        ts_arr = wide["timestamp"].values
        for i in range(len(wide)):
            S = S_arr[i]
            mid = mid_arr[i]
            if not np.isfinite(S) or not np.isfinite(mid):
                continue
            day = int(day_arr[i])
            tick_frac = ts_arr[i] / TIMESTAMPS_PER_DAY
            tte_days = START_TTE_DAYS[day] - tick_frac
            T = tte_days / DAYS_PER_YEAR
            if T <= 0:
                continue
            sigma = implied_vol(float(mid), float(S), float(k), float(T))
            if not math.isnan(sigma):
                ivs[i] = sigma
        iv_cols[k] = ivs
        n_ok = np.isfinite(ivs).sum()
        print(f"  IV for K={k}: {n_ok} / {len(wide)} ticks solved "
              f"(skipped {len(wide) - n_ok} NaN)")
    return iv_cols


def main():
    print("=" * 70)
    print("PHASE 3 — Realised Vol vs Implied Vol diagnostic")
    print("=" * 70)

    print("\n[1] Loading data...")
    df = load_all_days()
    print(f"  rows after filter: {len(df):,}")
    print(f"  products kept: {sorted(df['product'].unique())}")

    wide = pivot_mids(df)
    print(f"  wide grid shape: {wide.shape}")
    print(f"  columns: {[c for c in wide.columns if c not in ('day','timestamp','global_t')]}")

    print("\n[1b] Verifying tick step...")
    verify_tick_step(wide)

    # Sanity on VE
    print("\n[1c] VE sanity per day:")
    for d in (0, 1, 2):
        ve = wide.loc[wide["day"] == d, UNDERLYING].dropna()
        print(f"  day {d}: mean={ve.mean():.2f}, std={ve.std():.2f}, "
              f"min={ve.min():.2f}, max={ve.max():.2f}, n_ticks={len(ve)}")

    print("\n[2] Computing realised volatility...")
    rvs, log_ret = compute_rv(wide[UNDERLYING])
    print(f"  log-return stats: mean={log_ret.mean():.2e}, "
          f"std={log_ret.std():.2e}, n_finite={np.isfinite(log_ret).sum()}")
    naive_annual_vol = log_ret.std() * ANNUALISATION
    print(f"  naive full-sample annualised vol = {naive_annual_vol:.4f}")
    for w, rv in rvs.items():
        med = np.nanmedian(rv)
        print(f"  RV window={w:>5}: median={med:.4f}, "
              f"mean={np.nanmean(rv):.4f}, n_finite={np.isfinite(rv).sum()}")

    print("\n[3] Computing implied volatility per strike...")
    iv_cols = compute_iv_grid(wide)
    iv_df = pd.DataFrame(iv_cols, index=wide.index)
    iv_df.columns = [f"IV_{k}" for k in ACTIVE_STRIKES]
    avg_iv = iv_df.mean(axis=1)
    print(f"  average IV across 6 strikes: median={np.nanmedian(avg_iv):.4f}, "
          f"mean={np.nanmean(avg_iv):.4f}, std={np.nanstd(avg_iv):.4f}")

    # Magnitude sanity check
    rv_med = np.nanmedian(rvs[1000])
    iv_med = np.nanmedian(avg_iv)
    if rv_med > 0 and (iv_med / rv_med > 100 or iv_med / rv_med < 0.01):
        print(f"\n  !! WARNING: IV/RV ratio = {iv_med/rv_med:.2f} — "
              f"annualisation likely wrong. Halting.")
        sys.exit(1)
    print(f"\n  magnitude check: median RV(1000)={rv_med:.4f}, "
          f"median avg-IV={iv_med:.4f}, ratio={iv_med/rv_med:.2f} "
          f"(want O(1) — same units)")

    # Build the analysis frame
    out = wide[["day", "timestamp", "global_t", UNDERLYING]].copy()
    for w, rv in rvs.items():
        out[f"RV_{w}"] = rv.values
    for col in iv_df.columns:
        out[col] = iv_df[col].values
    out["avg_IV"] = avg_iv.values
    for k in ACTIVE_STRIKES:
        out[f"spread_{k}"] = out[f"IV_{k}"] - out["RV_1000"]
    out["spread_avg"] = out["avg_IV"] - out["RV_1000"]

    # ---- CHART ----
    print("\n[5] Building chart...")
    fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True)
    x = out["global_t"].values

    # Panel A: VE mid
    axes[0].plot(x, out[UNDERLYING].values, color="black", lw=0.7)
    axes[0].set_ylabel("VE mid price")
    axes[0].set_title("Panel A — VELVETFRUIT_EXTRACT mid")
    for d in (1, 2):
        axes[0].axvline(d * TIMESTAMPS_PER_DAY, color="grey",
                        ls="--", lw=0.8)
    axes[0].grid(alpha=0.3)

    # Panel B: RV (3 windows) + avg IV
    rv_colors = {100: "tab:cyan", 1000: "tab:blue", 10_000: "tab:purple"}
    for w in (100, 1000, 10_000):
        axes[1].plot(x, out[f"RV_{w}"].values,
                     color=rv_colors[w], lw=0.8, label=f"RV {w}-tick")
    axes[1].plot(x, out["avg_IV"].values, color="tab:red", lw=1.0,
                 label="avg IV (6 strikes)")
    axes[1].set_ylabel("annualised vol")
    axes[1].set_title("Panel B — Realised vs Implied volatility")
    axes[1].legend(loc="upper right", ncol=2, fontsize=9)
    for d in (1, 2):
        axes[1].axvline(d * TIMESTAMPS_PER_DAY, color="grey",
                        ls="--", lw=0.8)
    axes[1].grid(alpha=0.3)

    # Panel C: per-strike spread IV - RV(1000)
    cmap = plt.get_cmap("viridis")
    for i, k in enumerate(ACTIVE_STRIKES):
        c = cmap(i / max(1, len(ACTIVE_STRIKES) - 1))
        axes[2].plot(x, out[f"spread_{k}"].values, lw=0.7, color=c, label=f"K={k}")
    axes[2].axhline(0.0, color="black", lw=1.0)
    axes[2].set_ylabel("IV − RV(1000)")
    axes[2].set_xlabel("global tick index (day 0 → day 2)")
    axes[2].set_title("Panel C — Per-strike IV minus realised (1000-tick window)")
    axes[2].legend(loc="upper right", ncol=3, fontsize=9)
    for d in (1, 2):
        axes[2].axvline(d * TIMESTAMPS_PER_DAY, color="grey",
                        ls="--", lw=0.8)
    axes[2].grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=130)
    print(f"  saved chart -> {OUT_PNG}")

    # ---- CONCLUSION ----
    print("\n" + "=" * 70)
    print("[6] CONCLUSION")
    print("=" * 70)

    spread = out["spread_avg"].dropna().values
    n = len(spread)
    mean = float(np.mean(spread))
    median = float(np.median(spread))
    std = float(np.std(spread, ddof=1))
    sem = std / math.sqrt(n) if n > 0 else float("nan")
    ci_lo = mean - 1.96 * sem
    ci_hi = mean + 1.96 * sem
    z = mean / sem if sem > 0 else float("nan")

    print(f"\nAvg-IV minus RV(1000) over all aligned ticks:")
    print(f"  n              = {n:,}")
    print(f"  mean           = {mean:+.5f}")
    print(f"  median         = {median:+.5f}")
    print(f"  std            = {std:.5f}")
    print(f"  SEM            = {sem:.6f}")
    print(f"  95% CI         = [{ci_lo:+.5f}, {ci_hi:+.5f}]")
    print(f"  |mean|/SEM (z) = {abs(z):.2f}")

    print("\nPer-strike IV − RV(1000):")
    per_strike = {}
    for k in ACTIVE_STRIKES:
        s = out[f"spread_{k}"].dropna().values
        m = float(np.mean(s)) if len(s) else float("nan")
        per_strike[k] = m
        print(f"  K={k}: mean spread = {m:+.5f}  (n={len(s):,})")

    largest_premium = max(per_strike, key=lambda k: per_strike[k])
    largest_discount = min(per_strike, key=lambda k: per_strike[k])
    print(f"\n  largest IV PREMIUM  vs RV: K={largest_premium} "
          f"({per_strike[largest_premium]:+.5f})")
    print(f"  largest IV DISCOUNT vs RV: K={largest_discount} "
          f"({per_strike[largest_discount]:+.5f})")

    # ---- GATE ----
    if not math.isfinite(sem) or sem == 0:
        meaningful = False
    else:
        meaningful = abs(mean) > 2.0 * sem
    if not meaningful:
        lean = "NEUTRAL (no statistically meaningful bias)"
    elif mean > 0:
        lean = "SHORT VOL (IV > RV → vouchers structurally rich; default to selling)"
    else:
        lean = "LONG VOL (IV < RV → vouchers structurally cheap; default to buying)"

    flag = "STATISTICALLY MEANINGFUL" if meaningful else "NOISE — neutral lean"

    print("\n" + "=" * 70)
    print("GATE")
    print("=" * 70)
    print(f"  IV − RV bias (mean ± std) : {mean:+.5f} ± {std:.5f}")
    print(f"  95% CI                    : [{ci_lo:+.5f}, {ci_hi:+.5f}]")
    print(f"  z = |mean| / SEM          : {abs(z):.2f}  "
          f"(threshold for meaningful: 2.00)")
    print(f"  flag                      : {flag}")
    print(f"  recommended trading lean  : {lean}")
    print("=" * 70)


if __name__ == "__main__":
    main()
