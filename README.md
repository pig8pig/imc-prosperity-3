# IMC Prosperity 3 — FrankfurtHedgehogs

Algorithmic trading bot for the [IMC Prosperity 3](https://prosperity.imc.com/) competition.

## Setup

### Prerequisites

- Python 3.10+
- Git

### Install

1. **Clone the repo**
   ```bash
   git clone https://github.com/your-username/imc-prosperity-3.git
   cd imc-prosperity-3
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   ```

3. **Activate it**
   - Windows:
     ```bash
     venv\Scripts\activate
     ```
   - macOS/Linux:
     ```bash
     source venv/bin/activate
     ```

4. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Running the Backtest

Use `prosperity3bt` to backtest a trader file against a specific round:

```bash
prosperity3bt FrankfurtHedgehogs_polished.py <round>
```

- `<round>` — round number (e.g. `0`, `1`, `2`, ...)
- Add `--vis` to open the interactive results visualiser in your browser

**Example:**
```bash
prosperity3bt FrankfurtHedgehogs_polished.py 0 --vis
```

Backtest logs are saved automatically to `backtests/`.

## Project Structure

```
.
├── FrankfurtHedgehogs_polished.py  # Main trader implementation
├── datamodel.py                    # IMC datamodel (provided by competition)
├── requirements.txt
├── backtests/                      # Saved backtest logs
└── imc3/                           # (local venv — not tracked by git)
```

## Strategy Overview

| Instrument | Strategy |
|---|---|
| `RAINFOREST_RESIN` | Market-making around a stable fair value |
| `KELP` | Market-making with informed-trader signal (Olivia) |
| `SQUID_INK` | Follow informed trader signal only |
| `PICNIC_BASKET1/2` | ETF arbitrage vs. NAV of constituents |
| `VOLCANIC_ROCK` + vouchers | Black-Scholes options pricing, IV scalping, mean reversion |
| `MAGNIFICENT_MACARONS` | Conversion arbitrage (local vs. external market) |
