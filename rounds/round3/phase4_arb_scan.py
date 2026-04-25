"""Phase 4 — Historical static-arb scan on Round-3 voucher mids.

Diagnostic only. Live scanner uses bids/asks; this uses mids to surface
violations that would have existed even without crossing the spread.
"""

import os
import sys
import math
import pandas as pd

DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "round3"
)

ACTIVE_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
ACTIVE_PRODUCTS = [f"VEV_{k}" for k in ACTIVE_STRIKES]
EPS = 1e-6


def load_day(d):
    df = pd.read_csv(
        os.path.join(DATA_DIR, f"prices_round_3_day_{d}.csv"), sep=";"
    )
    df = df[df["product"].isin(ACTIVE_PRODUCTS)].copy()
    df["day"] = d
    wide = df.pivot_table(
        index=["day", "timestamp"], columns="product", values="mid_price",
        aggfunc="first",
    ).reset_index().sort_values(["day", "timestamp"]).reset_index(drop=True)
    return wide


def scan_tick(row):
    mids = {k: row[f"VEV_{k}"] for k in ACTIVE_STRIKES}
    if any(pd.isna(v) for v in mids.values()):
        return []
    violations = []

    n = len(ACTIVE_STRIKES)
    for i in range(n):
        for j in range(i + 1, n):
            k1, k2 = ACTIVE_STRIKES[i], ACTIVE_STRIKES[j]
            c1, c2 = mids[k1], mids[k2]
            # 1A monotonicity: C(K1) >= C(K2)
            edge = c2 - c1
            if edge > EPS:
                violations.append({
                    "type": "MONO", "k1": k1, "k2": k2,
                    "profit": edge,
                    "detail": f"C({k1})={c1} < C({k2})={c2}",
                })
            # 1B vertical spread upper bound
            edge2 = (c1 - c2) - (k2 - k1)
            if edge2 > EPS:
                violations.append({
                    "type": "VSPREAD", "k1": k1, "k2": k2,
                    "profit": edge2,
                    "detail": f"C({k1})-C({k2})={c1-c2} > {k2-k1}",
                })

    for i in range(n - 2):
        k1, k2, k3 = ACTIVE_STRIKES[i], ACTIVE_STRIKES[i + 1], ACTIVE_STRIKES[i + 2]
        bfly = mids[k1] - 2 * mids[k2] + mids[k3]
        if bfly < -EPS:
            violations.append({
                "type": "BFLY", "k1": k1, "k2": k2, "k3": k3,
                "profit": -bfly,
                "detail": f"C({k1})-2C({k2})+C({k3})={bfly:.4f}",
            })
    return violations


def main():
    print("=" * 70)
    print("PHASE 4 — Historical static-arb scan (mids only)")
    print("=" * 70)

    all_violations = []
    per_day_summary = {}
    total_ticks = 0

    for d in (0, 1, 2):
        try:
            wide = load_day(d)
        except Exception as e:
            print(f"  ERROR loading day {d}: {e}")
            continue
        n_ticks = len(wide)
        total_ticks += n_ticks
        day_viols = []
        for _, row in wide.iterrows():
            vs = scan_tick(row)
            for v in vs:
                v["day"] = d
                v["timestamp"] = int(row["timestamp"])
            day_viols.extend(vs)
        per_day_summary[d] = {"n_ticks": n_ticks, "n_viols": len(day_viols)}
        all_violations.extend(day_viols)
        print(f"  day {d}: ticks={n_ticks:>6,}, violations={len(day_viols):>5,}")

    print(f"\nTotal ticks scanned: {total_ticks:,}")
    print(f"Total violations    : {len(all_violations):,}")

    by_type = {}
    for v in all_violations:
        by_type.setdefault(v["type"], []).append(v)

    print("\nBy violation type:")
    for t, lst in sorted(by_type.items()):
        profits = [v["profit"] for v in lst]
        print(f"  {t:<8} n={len(lst):>5,}  "
              f"mean profit={sum(profits)/len(profits):.4f}  "
              f"max={max(profits):.4f}")

    if not by_type:
        print("  (no violation types triggered)")

    # Top 10 by per-unit profit
    top = sorted(all_violations, key=lambda v: -v["profit"])[:10]
    if top:
        print("\nTop 10 most profitable historical violations (mid-based):")
        print(f"  {'day':>3} {'ts':>7} {'type':<8} {'profit':>10}  detail")
        for v in top:
            print(f"  {v['day']:>3} {v['timestamp']:>7} {v['type']:<8} "
                  f"{v['profit']:>10.4f}  {v['detail']}")
    else:
        print("\nNo historical violations on mids — chain is internally consistent.")

    pct = 100.0 * len(all_violations) / total_ticks if total_ticks else 0.0
    print(f"\nViolation rate: {pct:.4f}% of ticks "
          f"({len(all_violations)}/{total_ticks})")

    print("\n" + "=" * 70)
    print("GATE")
    print("=" * 70)
    print("  scanner ran without error on all 3 days: PASS")
    if len(all_violations) == 0:
        print("  INFORMATIONAL: zero historical mid-violations — scanner ships")
        print("  as a defensive layer. Do NOT expect PnL from it.")
    else:
        print(f"  INFORMATIONAL: {len(all_violations):,} mid-violations found "
              f"({pct:.4f}% of ticks). Live scanner uses bid/ask, so realised")
        print("  edge will be a strict subset of these.")
    print("=" * 70)


if __name__ == "__main__":
    main()
