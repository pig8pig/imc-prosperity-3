"""
=======================================================================
IMC Prosperity 4 — Round 5 Comprehensive Product Analysis
=======================================================================

Computes every metric we've discussed, for all 50 products:
  1. Per-product:  level, vol, spread, depth, drift t-stat, autocorrelation,
                   mean-reversion half-life, intraday range
  2. Per-category: basket sum constraint test, PC1 variance, avg correlation,
                   linear basket regression (X = const - sum(others))
  3. Pairs:        top within-category and cross-category correlations
  4. Time-series:  per-day drift, sub-window winrate, trend/MR/RW classification
  5. Plots:        50-panel mid grid, basket sum overlays, MR vs vol scatter

Run:
    python r5_analysis.py --data-dir /path/to/data --days 2 3 4 --out-dir ./r5_out

Inputs expected in --data-dir:
    prices_round_5_day_{N}.csv  OR  prices_round_5_day_{N}.csv.gz
    trades_round_5_day_{N}.csv  (optional; trades=None if missing)

Outputs in --out-dir:
    summary_per_product.csv     -- 1 row per product, all metrics
    summary_per_category.csv    -- 1 row per category, basket structure
    pairs.csv                   -- top correlated/anti-correlated pairs
    classification.csv          -- strategy bucket per product
    plots/grid_50.png           -- 50-panel mid plot
    plots/basket_sums.png       -- category sum overlays
    plots/mr_vs_vol.png         -- mean-reversion vs vol scatter
=======================================================================
"""

import argparse
import os
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------

CATEGORIES = {
    "GALAXY_SOUNDS": ["GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
                      "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
                      "GALAXY_SOUNDS_SOLAR_FLAMES"],
    "SLEEP_POD":     ["SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
                      "SLEEP_POD_NYLON", "SLEEP_POD_COTTON"],
    "MICROCHIP":     ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
                      "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE"],
    "PEBBLES":       ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"],
    "ROBOT":         ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
                      "ROBOT_LAUNDRY", "ROBOT_IRONING"],
    "UV_VISOR":      ["UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
                      "UV_VISOR_RED", "UV_VISOR_MAGENTA"],
    "TRANSLATOR":    ["TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
                      "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
                      "TRANSLATOR_VOID_BLUE"],
    "PANEL":         ["PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"],
    "OXYGEN_SHAKE":  ["OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
                      "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE",
                      "OXYGEN_SHAKE_GARLIC"],
    "SNACKPACK":     ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
                      "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"],
}
PRODUCT_TO_CAT = {p: c for c, prods in CATEGORIES.items() for p in prods}

# ---------------------------------------------------------------------
# 1. LOADERS
# ---------------------------------------------------------------------

def _find_file(data_dir, prefix, day):
    """Return path to prices/trades CSV (prefer .csv.gz, fallback to .csv)."""
    for ext in ("csv.gz", "csv"):
        p = Path(data_dir) / f"{prefix}_day_{day}.{ext}"
        if p.exists():
            return p
    return None


def load_prices(data_dir, days):
    """Concatenate prices CSVs (handles .csv and .csv.gz) for given days."""
    frames = []
    for d in days:
        path = _find_file(data_dir, "prices_round_5", d)
        if path is None:
            raise FileNotFoundError(f"No prices file found for day {d} in {data_dir}")
        comp = "gzip" if str(path).endswith(".gz") else None
        frames.append(pd.read_csv(path, sep=";", compression=comp))
    df = pd.concat(frames, ignore_index=True)
    return df.sort_values(["product", "day", "timestamp"]).reset_index(drop=True)


def load_trades(data_dir, days):
    """Concatenate trades CSVs. Returns None if no files found."""
    frames = []
    for d in days:
        path = _find_file(data_dir, "trades_round_5", d)
        if path is None:
            continue
        comp = "gzip" if str(path).endswith(".gz") else None
        df = pd.read_csv(path, sep=";", compression=comp)
        df["day"] = d
        frames.append(df)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------
# 2. PER-PRODUCT METRICS
# ---------------------------------------------------------------------

def half_life_of_residual(mid, window=100):
    """
    Compute mean-reversion half-life of mid-price deviations from a rolling
    mean.  Method: detrend with rolling mean, fit AR(1) to residuals,
    half_life = ln(0.5) / ln(beta) if 0 < beta < 1.
    Returns NaN if non-stationary.
    """
    s = pd.Series(mid)
    resid = (s - s.rolling(window, min_periods=window).mean()).dropna().values
    if len(resid) < 200:
        return np.nan
    x = resid[:-1]
    y = resid[1:]
    # OLS slope: y = a + b*x
    if x.var() == 0:
        return np.nan
    b = np.cov(x, y, ddof=0)[0, 1] / x.var()
    if not (0 < b < 1):
        return np.nan
    return np.log(0.5) / np.log(b)


def variance_ratio(mid, k=10):
    """
    Lo-MacKinlay variance ratio. VR(k) = Var(P_t - P_{t-k}) / (k * Var(P_t - P_{t-1})).
    VR=1 random walk;  VR<1 mean reverting;  VR>1 trending.
    """
    r1 = np.diff(mid)
    rk = mid[k:] - mid[:-k]
    if r1.var() == 0:
        return np.nan
    return rk.var() / (k * r1.var())


def per_product_metrics(prices, trades=None):
    """
    Build a per-product metric table.
    Notes for interpretation:
      - rho1 < 0: returns mean-revert (good for MM)
      - rho1 > 0: returns trend (bad for MM)
      - var_ratio_10 < 1: prices revert; > 1 trend
      - half_life: # ticks to revert half the deviation; smaller = better for MM
      - drift_t_min: minimum |t-stat| of drift across days. Need > 2 for sig drift.
    """
    rows = []
    for prod, g in prices.groupby("product"):
        # Per-day arrays
        per_day = {}
        for d, dg in g.groupby("day"):
            m = dg["mid_price"].values
            r = np.diff(m)
            per_day[d] = {
                "open": m[0], "close": m[-1],
                "drift": m[-1] - m[0],
                "ret_mean": r.mean(),
                "ret_std": r.std(),
                "t_stat": r.mean() / (r.std() / np.sqrt(len(r))) if r.std() > 0 else 0,
                "intraday_range": m.max() - m.min(),
                "rho1": np.corrcoef(r[:-1], r[1:])[0, 1] if len(r) > 100 else np.nan,
                "vr10": variance_ratio(m, 10),
                "halflife": half_life_of_residual(m, 100),
            }
        # Cross-day aggregates
        all_mid = g["mid_price"].values
        all_ret = np.diff(all_mid)  # contains 1 cross-day jump per day boundary; minor
        spread = (g["ask_price_1"] - g["bid_price_1"]).values
        bid_v = g["bid_volume_1"].fillna(0).values
        ask_v = g["ask_volume_1"].fillna(0).values

        ts = trades[trades["symbol"] == prod] if trades is not None else None

        row = {
            "product": prod,
            "category": PRODUCT_TO_CAT[prod],
            "mid_mean": np.nanmean(all_mid),
            "mid_std": np.nanstd(all_mid),
            "mid_min": np.nanmin(all_mid),
            "mid_max": np.nanmax(all_mid),
            "ret_std": np.nanstd(all_ret),
            "ret_abs_mean": np.nanmean(np.abs(all_ret)),
            "spread_mean": np.nanmean(spread),
            "spread_med": np.nanmedian(spread),
            "L1_bid_depth": np.nanmean(bid_v),
            "L1_ask_depth": np.nanmean(ask_v),
            # Mean-reversion / trend signals (averaged across days)
            "rho1_avg": np.nanmean([d["rho1"] for d in per_day.values()]),
            "vr10_avg": np.nanmean([d["vr10"] for d in per_day.values()]),
            "halflife_avg": np.nanmean([d["halflife"] for d in per_day.values()]),
            # Drift consistency
            "drift_total": sum(d["drift"] for d in per_day.values()),
            "drift_t_min": min(per_day.values(), key=lambda x: abs(x["t_stat"]))["t_stat"],
            "drift_t_max_abs": max(abs(d["t_stat"]) for d in per_day.values()),
            "drift_consistent_sign": all(np.sign(d["drift"]) == np.sign(per_day[list(per_day)[0]]["drift"])
                                         for d in per_day.values()),
            "intraday_range_avg": np.mean([d["intraday_range"] for d in per_day.values()]),
            # Trade flow
            "n_trades": len(ts) if ts is not None else np.nan,
            "trade_volume": ts["quantity"].sum() if ts is not None else np.nan,
        }
        # Per-day drift breakout (one column per day)
        for d, dd in per_day.items():
            row[f"drift_d{d}"] = dd["drift"]
            row[f"t_d{d}"] = dd["t_stat"]
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["category", "product"]).reset_index(drop=True)


# ---------------------------------------------------------------------
# 3. PER-CATEGORY METRICS (basket structure)
# ---------------------------------------------------------------------

def per_category_metrics(prices):
    """
    For each category, test whether the 5 mids form a basket.
    Key metrics:
      - sum_std / sum_mean: tightness of sum constraint (PEBBLES = 0.006%)
      - avg_corr: mean off-diagonal pairwise correlation (negative = basket-like)
      - pc1_var_pct: variance explained by 1st PC (high = common factor)
      - basket_residual_std: residual std when fitting product = const - sum(others)
                             Small => members on a near-perfect hyperplane.
    """
    wide = prices.pivot_table(index=["day", "timestamp"], columns="product",
                              values="mid_price")
    rows = []
    for cat, prods in CATEGORIES.items():
        sub = wide[prods].dropna()
        s = sub.sum(axis=1)
        c = sub.corr().values
        n = len(prods)
        avg_corr = (c.sum() - n) / (n * n - n)
        eig = np.sort(np.linalg.eigvalsh(sub.cov().values))[::-1]
        pc1_pct = 100 * eig[0] / eig.sum()

        # Basket regression: pick a product, regress on the others
        X = sub.values
        y = X[:, 0]
        A = np.hstack([np.ones((X.shape[0], 1)), X[:, 1:]])
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        resid = y - A @ coef

        if avg_corr < -0.18 and s.std() < 100:
            structure = "STRICT BASKET"
        elif avg_corr < -0.18:
            structure = "SOFT BASKET / negative-corr"
        elif avg_corr > 0.30:
            structure = "COMMON FACTOR"
        else:
            structure = "INDEPENDENT / weak"

        rows.append({
            "category": cat,
            "n_products": n,
            "sum_mean": s.mean(),
            "sum_std": s.std(),
            "sum_pct": 100 * s.std() / s.mean(),
            "avg_pairwise_corr": avg_corr,
            "pc1_var_pct": pc1_pct,
            "basket_resid_std": resid.std(),
            "structure": structure,
        })
    return pd.DataFrame(rows).sort_values("sum_pct").reset_index(drop=True)


# ---------------------------------------------------------------------
# 4. PAIRS — top correlated and anti-correlated
# ---------------------------------------------------------------------

def find_pairs(prices, top_n=20):
    """
    Compute the full 50x50 correlation matrix and return the top N most
    positively and negatively correlated *cross-category* pairs (within-category
    pairs are also flagged so you can compare).
    """
    wide = prices.pivot_table(index=["day", "timestamp"], columns="product",
                              values="mid_price").dropna()
    corr = wide.corr()
    pairs = []
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = cols[i], cols[j]
            pairs.append({
                "a": a, "b": b,
                "cat_a": PRODUCT_TO_CAT[a], "cat_b": PRODUCT_TO_CAT[b],
                "same_cat": PRODUCT_TO_CAT[a] == PRODUCT_TO_CAT[b],
                "corr": corr.loc[a, b],
            })
    pdf = pd.DataFrame(pairs)
    top_pos = pdf.sort_values("corr", ascending=False).head(top_n)
    top_neg = pdf.sort_values("corr").head(top_n)
    return pd.concat([top_pos, top_neg]).reset_index(drop=True)


# ---------------------------------------------------------------------
# 5. CLASSIFICATION (strategy bucket per product)
# ---------------------------------------------------------------------

def classify_products(per_prod, per_cat):
    """Assign each product to a strategy bucket using rules of thumb."""
    cat_lookup = per_cat.set_index("category")
    rows = []
    for _, r in per_prod.iterrows():
        cat = r["category"]
        cat_struct = cat_lookup.loc[cat, "structure"]
        bucket = "TBD"
        rationale = ""
        if cat_struct == "STRICT BASKET":
            bucket = "BASKET_ARB"
            rationale = "Sum constraint exploitable; cross-hedge guaranteed."
        elif cat_struct == "SOFT BASKET / negative-corr":
            bucket = "SOFT_BASKET_RV"
            rationale = "Relative-value within category; sum mildly anchored."
        elif cat_struct == "COMMON FACTOR":
            bucket = "FACTOR_SPREAD"
            rationale = "Products move together; trade outliers vs basket mean."
        elif r["rho1_avg"] < -0.05 and r["spread_mean"] / r["ret_std"] > 0.6:
            bucket = "MEAN_REVERSION_MM"
            rationale = f"rho1={r['rho1_avg']:.3f}, spread/vol favorable."
        elif r["spread_mean"] / r["ret_std"] > 1.5 and abs(r["rho1_avg"]) < 0.05:
            bucket = "STANDARD_MM"
            rationale = f"Wide spread vs vol (sp/vol={r['spread_mean']/r['ret_std']:.2f})."
        elif r["drift_consistent_sign"] and r["drift_t_max_abs"] > 1.0:
            bucket = "DIRECTIONAL_OVERLAY"
            rationale = f"Consistent sign across days, max|t|={r['drift_t_max_abs']:.2f}."
        else:
            bucket = "SKIP_OR_PASSIVE"
            rationale = "No clear edge identified."
        rows.append({
            "product": r["product"], "category": cat, "bucket": bucket,
            "rationale": rationale,
            "rho1_avg": r["rho1_avg"], "vr10_avg": r["vr10_avg"],
            "halflife_avg": r["halflife_avg"], "spread_mean": r["spread_mean"],
            "ret_std": r["ret_std"], "drift_total": r["drift_total"],
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------
# 6. PLOTS
# ---------------------------------------------------------------------

def plot_grid(prices, out_path):
    fig, axes = plt.subplots(10, 5, figsize=(22, 30), sharex=True)
    day_colors = {2: "#1f77b4", 3: "#2ca02c", 4: "#d62728"}
    for r, (cat, prods) in enumerate(CATEGORIES.items()):
        for c, prod in enumerate(prods):
            ax = axes[r, c]
            sub = prices[prices["product"] == prod]
            for d, dg in sub.groupby("day"):
                color = day_colors.get(d, "#888888")
                ax.plot(dg["timestamp"].values, dg["mid_price"].values,
                        lw=0.5, color=color, label=f"day {d}")
            ax.set_title(prod, fontsize=8)
            ax.tick_params(labelsize=7)
            ax.grid(alpha=0.3)
            if c == 0:
                ax.set_ylabel(cat, fontsize=9, rotation=0, ha="right", va="center")
            if r == 0 and c == 4:
                ax.legend(fontsize=7, loc="upper right")
    plt.suptitle("All 50 products — mid prices by tick (colored by day)", fontsize=14, y=0.995)
    plt.tight_layout()
    plt.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def plot_basket_sums(prices, out_path):
    wide = prices.pivot_table(index=["day", "timestamp"], columns="product",
                              values="mid_price")
    fig, axes = plt.subplots(5, 2, figsize=(16, 16))
    axes = axes.flatten()
    for i, (cat, prods) in enumerate(CATEGORIES.items()):
        ax = axes[i]
        for d in sorted(prices["day"].unique()):
            try:
                s = wide.loc[d, prods].sum(axis=1)
                ax.plot(s.index, s.values, lw=0.5, label=f"day {d}")
            except KeyError:
                continue
        ax.set_title(f"{cat}: sum of 5 mids")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def plot_mr_vs_vol(per_prod, out_path):
    fig, ax = plt.subplots(figsize=(11, 7))
    cats = per_prod["category"].unique()
    cmap = plt.colormaps["tab10"]
    colors = {c: cmap(i % 10) for i, c in enumerate(cats)}
    for _, r in per_prod.iterrows():
        ax.scatter(r["rho1_avg"], r["ret_std"], color=colors[r["category"]], s=60, alpha=0.8)
        ax.annotate(r["product"].split("_")[-1], (r["rho1_avg"], r["ret_std"]),
                    fontsize=7, alpha=0.7, ha="left", va="bottom")
    ax.axvline(0, color="black", lw=0.5)
    ax.axvline(-0.05, color="gray", lw=0.5, ls="--")
    ax.set_xlabel("Lag-1 return autocorrelation (ρ₁)  ←mean-reverting | trending→")
    ax.set_ylabel("Return std (per-tick volatility)")
    ax.set_title("Mean-reversion vs volatility map")
    handles = [plt.Line2D([0], [0], marker="o", color="w",
                          markerfacecolor=colors[c], markersize=8, label=c)
               for c in cats]
    ax.legend(handles=handles, bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------
# 7. MAIN
# ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, help="dir with prices_round_5_day_X[.gz] and trades_*")
    ap.add_argument("--days", nargs="+", type=int, default=[2, 3, 4])
    ap.add_argument("--out-dir", default="./r5_out")
    args = ap.parse_args()

    out = Path(args.out_dir)
    (out / "plots").mkdir(parents=True, exist_ok=True)

    print(f"Loading prices for days {args.days}...")
    prices = load_prices(args.data_dir, args.days)
    print(f"  Loaded {len(prices):,} rows, {prices['product'].nunique()} products.")

    print("Loading trades...")
    trades = load_trades(args.data_dir, args.days)
    print(f"  {'No trades' if trades is None else f'{len(trades):,} trades'}.")

    print("Computing per-product metrics...")
    per_prod = per_product_metrics(prices, trades)
    per_prod.to_csv(out / "summary_per_product.csv", index=False)

    print("Computing per-category metrics...")
    per_cat = per_category_metrics(prices)
    per_cat.to_csv(out / "summary_per_category.csv", index=False)

    print("Finding pairs...")
    pairs = find_pairs(prices, top_n=20)
    pairs.to_csv(out / "pairs.csv", index=False)

    print("Classifying products...")
    classification = classify_products(per_prod, per_cat)
    classification.to_csv(out / "classification.csv", index=False)

    print("Plotting grid...")
    plot_grid(prices, out / "plots" / "grid_50.png")
    print("Plotting basket sums...")
    plot_basket_sums(prices, out / "plots" / "basket_sums.png")
    print("Plotting MR vs vol...")
    plot_mr_vs_vol(per_prod, out / "plots" / "mr_vs_vol.png")

    print()
    print("=" * 80)
    print("CATEGORY STRUCTURE SUMMARY")
    print("=" * 80)
    print(per_cat.to_string(index=False))
    print()
    print("=" * 80)
    print("CLASSIFICATION COUNTS")
    print("=" * 80)
    print(classification["bucket"].value_counts())
    print()
    print(f"All results saved to {out.resolve()}")


if __name__ == "__main__":
    main()
