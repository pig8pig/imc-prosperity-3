# Frankfurt Hedgehogs 📈

This writeup shares our algorithm and insights that brought us to 2nd place globally in IMC Prosperity 3 (2025). Outperforming (almost) all other 12,000+ teams, we achieved a final score of 1,433,876 SeaShells but unfortunately we didn't win the 10,000$ prize for it as we had already earned prize money in last year's competition :)

<table width="50%">
  <tbody>
    <tr>
      <td align="center" valign="top" width="200px">
        <a href="https://www.linkedin.com/in/timo-diehm">
          <img src="https://github.com/user-attachments/assets/9a919806-70ff-4672-bbde-57ec67f891b6" width="150;" alt="Timo Diehm"/>
          <br />
          <p><b>Timo Diehm</b></p></a>
      </td>
      <td align="center" valign="top" width="200px">
        <a href="https://www.linkedin.com/in/arne-witt">
          <img src="https://github.com/user-attachments/assets/61ee7433-469e-4a47-9bf6-a203aea6a0d5" width="150;" alt="Arne Witt"/>
          <br />
          <p><b>Arne Witt</b></p></a>
      </td>
      <td align="center" valign="top" width="200px">
        <a href="https://www.linkedin.com/in/marvin-schuster">
          <img src="https://github.com/user-attachments/assets/61ee7433-469e-4a47-9bf6-a203aea6a0d5" width="100px;" alt="Marvin Schuster"/>
          <br />
          <p><b>Marvin Schuster</b></br></p></a><span>*only mental support this time</span>
      </td>
    </tr>
  </tbody>
</table>

<br/>

After countless requests, we decided to share our final algorithm along with all of our insights to give back to the Prosperity 3 community. We also believe that sharing advances the competition itself — ensuring that more participants start on the same page for future editions, and encouraging innovation on IMC’s side.
While Prosperity 3 already introduced many new products and trading styles, there is still a lot of untapped potential — especially in designing bot behaviors that create deeper and more exploitable opportunities for highly advanced teams.
We realize that fellow or future participants have varying levels of experience with quant and algorithmic trading, so we tried to make this write-up as detailed and accessible as possible. Some topics are just too deep to explain in a short paragraph, so we included links to external resources that less experienced readers should carefully study.

<br/>

This report goes far beyond just presenting our final strategies.
We not only break down those strategies and insights that worked for us, but also share the thought processes and decisions behind them.
That said, this document is mainly intended for fellow or future Prosperity participants, since it focuses specifically on Prosperity 3.
If you're more interested in how we consistently stayed at the top across multiple competitions — and want general advice on how to compete against thousands of teams — check out our separate blog post:
<br />
<a href="https://www.linkedin.com/in/timo-diehm">How to (Almost) Win Against Thousands of Other Teams (link). </a>

## the competition 🏆

IMC Prosperity 3 (2025) was a global algorithmic trading competition that ran over five rounds and fifteen days, with 12,000+ teams participating worldwide.
The challenge tasked teams with designing trading algorithms to maximize profits across a variety of simulated products — replicating real-world opportunities such as market making, statistical arbitrage, scalping, and locational arbitrage etc.

The competition was gamified: each team represented an "island" trading fictional products like Kelp, Squid Ink, Picnic Baskets (an ETF analog), and Volcanic Rock Vouchers (an options analog), using SeaShells as the in-game currency.
It started with just three products in Round 1 and progressively expanded to 15 products by the final round.

In each round, teams submitted an updated version of their trading algorithm, which was then independently evaluated against a marketplace of bot participants.
Teams could study and optimize their algorithms by analyzing bot behaviors and interactions (e.g. predictable quoting or trading patterns) as well as statistical patterns in the price series themselves — both within a single product and across multiple related products (such as deviations between an ETF and its underlying constituents).The profit and loss (PnL) from this evaluation determined each team's standing relative to all others on the global leaderboard.

In addition to algorithmic trading, each round featured a manual trading challenge.
Although these accounted for only a small fraction of total PnL, they were a fun aspect of the competition, often involving optimization under uncertainty, game-theoretic decision-making, or news-based trading tasks.

For full documentation on the algorithmic trading environment and more competition context, please refer to the Prosperity 3 Wiki.

## Structure

- [Tools](#tools)
- [Algorithmic Part](#algorithmic-challenge)
- [Round 1](#round-1)
- [Round 2](#round-2)
- [Round 3](#round-3)
- [Round 4](#round-4)
- [Round 5](#round-5)
- [Manual Part](#manual-challenge)
- [FAQ](#frequently-asked-questions)
- [How to properly backtest?](#how-to-properly-backtest)
- [What Price to use?](#what-price-to-use)
- [How to break into quant trading?](#how-to-break-into-quant-trading)
- [Discord useful?](#discord-useful)
- [What else did we try?](#what-else-did-we-try)

## tools

Having the right tools prepared before the competition is critical for maximum efficiency during the competition itself.
Prosperity 2’s data was publicly available, allowing teams to familiarize themselves with the data formats, set up the tutorial environment early, and test their algorithms and logging infrastructure well before the official start of Prosperity 3.

### backtester 🔙

For backtesting, we mainly relied on our own forked version of Jasper Merle’s open-source backtester (jmerle/prosperity-backtester) alongside the Prosperity website’s own backtesting functionality.
Each served different, specific purposes in our workflow — for a detailed explanation of how we approached backtesting, please refer to the Backtesting Section.

### dashboard 💨

We developed our own dashboard as a preparation for Prosperity 2, and further updated and improved it before Prosperity 3 — adding features that we didn’t have time to implement during the first competition.
Since this dashboard will be heavily referenced when we explain our strategies and insights across all products, we’ll first give a detailed description of it here.

Prosperity — like real-world trading — puts strong emphasis on market microstructure.
A proper, intuitive order book visualization tool is essential for building the deep intuition necessary to recognize and exploit profitable patterns.

Unlike many standard trading dashboards, we designed ours completely from scratch, based on what was actually most useful for this particular competition.
Aesthetics were never our priority — everything was optimized purely for functionality and speed during use.
(Please keep that in mind — we know it’s ugly!)

![dashboard explanation](https://github.com/user-attachments/assets/6c283b73-07e3-4b3a-b8b5-9b38cc51b314)
<p align="center">
  <em>we used to have actual section headers, but at some point we (Jerry and Eric) got hungry and started editing them</em>
</p>

In the main plot, you can see **price levels**:

- **Ask (sell) quotes** are plotted in **red**.
- **Bid (buy) quotes** are plotted in **blue**.

Markers represent **trades**:

- **Squares** = trades by makers.
- **Triangles** = trades by takers.
- **Crosses** = our own trades.

Each numbered section in the dashboard corresponds to a specific functionality:

1. **Hoverable Tooltip** 🖱️  
   Displays who traded, how much, and at what price at the hovered timestamp.

2. **PnL Panel** 💰  
   Shows the profit and loss for the currently selected product.

3. **Position Panel** 📊  
   Displays the net position for the selected product over time.

4. **Log Viewer** 🧾  
   Parses our own logger outputs into a clean, timestamp-synced view.  
   Always matches the time currently hovered over in the main plot.

5. **Selection Controls** 🎯  
   Allows selecting:
   - The log file.
   - The product (e.g., Kelp).
   - Specific **logged indicators** to overlay onto prices.
   
   A powerful feature here is the **normalization dropdown**:  
   By selecting an indicator (e.g., `wall_mid` — our proxy for the "true price"), all prices can be normalized relative to it.  
   This is extremely useful for visualizing strategies like mean reversion (When having **PICNIC_BASKET1** selected normalizing by the sum of its constituents perfectly demonstrates the mean reversion of the baskets premium still maintaining the orderbook style).

6. **Trade Filtering and Visualization** 🔎  
   Controls what types of trades and order book elements to display:
   - Toggle order book levels.
   - Toggle all trades, specific trader groups or specific traders:
     - **M** (maker)
     - **S** (small taker)
     - **B** (big taker)
     - **I** (informed trader)
     - **F** (our own trades)
   - Set quantity filters to only show trades within a specified size range, especially helpful when trader IDs still unknown.

7. **Performance and Downsampling Controls** ⚡  
   Adjusts dynamic downsampling and visibility thresholds to prevent lag when visualizing large datasets.


Notes:
- We intentionally avoided any existing known dashboard styles; instead, we focused purely on designing what helped us most during analysis or checking of our algorithm during intense rounds.
- The visualization choice (scatter plot as order book depth representation) was made based on the specific structure of Prosperity markets — where products typically have only 1–4 meaningful price levels.

# Algorithmic Challenge

## Round 1

### Rainforest Resin 🔮

Rainforest Resin was the simplest and most beginner-friendly product in Prosperity 3, perfectly suited to teach the fundamentals of market making. The product’s true price was permanently fixed at 10,000, meaning there were no intrinsic price movements to worry about. This setup clearly demonstrated the roles of makers and takers: takers would cross the true price by either buying above 10,000 or selling below it, while makers posted passive orders hoping to be matched. The only thing that mattered for profitability here was the distance between the trade price and the true price — commonly referred to as the "edge." In short, the further you could buy below 10,000 or sell above 10,000, the better.

A key insight not just for Rainforest Resin but for all Prosperity products was understanding how the simulation handled order flow. At the start of every new timestep, the simulation first cleared all previous orders. Then, it sequentially processed new submissions: first some deep-liquidity makers, then small takers, then our own bot’s actions (take or make), followed by other bots — usually more takers. This structure meant that speed and order cancellation were irrelevant: you had a full snapshot of the book and could submit any combination of passive or aggressive orders without racing against anyone. For Rainforest Resin, this confirmed that all focus should be on carefully optimizing the edge versus fill probability trade-off.

<table>
<tr valign="top">
<td width="100%" align="center">
  <strong>Figure 1: Rainforest Resin Orderbook over Time</strong>
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <img src="https://github.com/user-attachments/assets/54363d35-63ac-406f-b2de-ad6a06e7433d"
       alt="Dynamic dashboard"
       width="100%" />
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <em>Snippet of orderbook over time for Rainforest Resin.  
  Black stars are our quotes. Orange crosses are fills we got, profitable opportunities we immediately took, or trades at 10,000 we used to unwind inventory.</em>
</td>
</tr>
</table>

Our final strategy for Rainforest Resin was straightforward. Each timestep, we first immediately took any favorable trades available — buying below 10,000 or selling above it. Afterward, we placed passive quotes slightly better than any existing liquidity: overbidding on bids and undercutting on asks while maintaining positive edge. If inventory became too skewed, we flattened it at exactly 10,000 to free up risk capacity for the next opportunities. No sophisticated logic or aggressiveness was needed due to the stable true price and the clean snapshot-based trading model.

Anyone could have come up with this approach by carefully reading the competition's matching rules and observing the environment during the tutorial round. Realizing that the true price was constant, fills were processed sequentially, and that orders only lived for one timestep simplified the problem dramatically. Having a basic visualization of price levels and logging fill quality would have made it even more obvious. Rainforest Resin alone consistently contributed around 35,000 SeaShells per round to our total PnL.


### Kelp ⭐

Kelp was very similar in nature to Rainforest Resin, with the only major difference being that its price could move slightly from one timestep to the next. Instead of a fixed true price like Rainforest Resin, Kelp's true price followed a slow random walk. However, this movement was minor enough that the basic structure of the problem remained unchanged. Buyers and sellers still interacted as takers when crossing the fair price, and makers earned profits based on how far their trades deviated from the true price at the moment of execution.

The critical insight for Kelp was recognizing that, despite small movements, the future price was essentially unpredictable. Once teams realized that takers lacked predictive power and that the next true price could not be systematically forecasted, it became clear that the best available estimate for the true price was simply the current one. In fact, while there was a minor technical edge — stemming from the fact that the true price was internally a floating-point value and orders could only be posted at integer levels (creating slight mean-reversion tendencies after ticks) — this effect was too small to materially alter strategy. Just like with Rainforest Resin, the optimal approach was to treat the "wall mid" [LINK] as the fair price and quote around it.

<table>
<tr valign="top">
<td width="100%" align="center">
  <strong>Figure 2a: Kelp Orderbook over Time (Raw)</strong>
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <img src="https://github.com/user-attachments/assets/2a7c36dc-76b8-482d-934b-c9ee7ff527f6"
       alt="Dynamic dashboard"
       width="100%" />
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <em>Same as Figure 1, but showing Kelp's price movement over time.</em>
</td>
</tr>
</table>

<table>
<tr valign="top">
<td width="100%" align="center">
  <strong>Figure 2b: Kelp Orderbook over Time (Normalized)</strong>
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <img src="https://github.com/user-attachments/assets/80b5f2cb-ae7a-400b-aff0-311e977c2d58"
       alt="Static, normalized dashboard"
       width="100%" />
</td>
</tr>

<tr valign="top">
<td width="100%" align="center">
  <em>Same as Figure 2a, but with prices normalized by the Wall Mid indicator to make the series stationary.  
  Notice how it resembles Rainforest Resin, but with a tighter bid-ask spread.</em>
</td>
</tr>
</table>


Our final strategy for Kelp was nearly identical to that for Rainforest Resin. At each timestep, we first immediately took any favorable trades available relative to the current wall mid, then placed slightly improved passive orders (overbidding and undercutting) around the fair price. If inventory became too large, we neutralized it by trading at zero edge relative to the current price estimate. No major changes were needed compared to the first product.

Teams that approached Kelp correctly would have first verified whether takers or the market exhibited any predictability, either through simple empirical analysis or by observing that naive strategies (like quoting around the current price) worked well. Realizing that there was no meaningful adverse selection risk meant that treating Kelp identically to Rainforest Resin was the optimal path. On average, Kelp generated around 8,000 SeaShells per round, primarily limited by the tighter spreads compared to the first product.

<table>
<tr valign="top">
<td width="70%">
  <img src="https://github.com/user-attachments/assets/2a7c36dc-76b8-482d-934b-c9ee7ff527f6"
       alt="Dynamic dashboard"
       width="100%" />
</td>
<td width="30%">
  <strong>Figure 2a: Kelp Orderbook over Time (Raw)</strong><br/>
  <em>Same as Figure 1, but with Kelp's price movement.</em>
</td>
</tr>

<tr valign="top">
<td width="70%">
  <img src="https://github.com/user-attachments/assets/80b5f2cb-ae7a-400b-aff0-311e977c2d58"
       alt="Static, normalized dashboard"
       width="100%" />
</td>
<td width="30%">
  <strong>Figure 2b: Kelp Orderbook over Time (Normalized)</strong><br/>
  <em>Same as Figure 2a, but every price got normalized (subtracted) with Wall Mid to make it stationary. Here one can see it is very similar to Rainforest Resin, except tighter bid-ask spread.</em>
</td>
</tr>
</table>



### Squid Ink ⭐

Squid Ink differed from the previous two products mainly in that it had a tighter bid-ask spread relative to its average movement, combined with occasional sharp price jumps. This made pure market-making less attractive, not because of systematic losses, but because it introduced higher variance in realized PnL. In other words, fills could swing more widely in value depending on unpredictable price jumps, even if there was no predictable adverse selection in the classic sense. Officially, the product was described as mean-reverting in the short term, suggesting that mean-reversion strategies might work. However, after investigating the market dynamics more carefully, we discovered an entirely different and more reliable opportunity.

Our main insight was that one of the anonymous bot traders consistently exhibited a strikingly predictable pattern: buying 15 lots at the daily low and selling 15 lots at the daily high. We observed this behavior early on, without initially knowing who the trader was. It was only in the final round — when trader IDs were temporarily visible — that we learned this trader was named Olivia. Anticipating this kind of behavior and designing logic to detect it gave us a clear edge. Without revealing our exact identification method (to avoid encouraging blind copying), the general approach involved tracking the daily running minimum and maximum. When a trade occurred at a daily extreme — and in the expected direction relative to the mid price — we flagged it as a signal and positioned accordingly. False positives were managed by monitoring for corresponding new extrema that contradicted earlier signals.

<table>
<tr valign="top">
<td width="70%">
  <img src="https://github.com/user-attachments/assets/9f552b07-98e9-4488-b4b9-95b2e1435747"
       alt="Dynamic dashboard"
       width="100%" />
</td>
<td width="30%">
  <strong>Figure 3a: Squid Ink Prices with Informed Trader</strong><br/>
  <em>This plot shows that Olivia bought exactly at daily min and sold exactly at daily max.</em>
</td>
</tr>

<tr valign="top">
<td width="70%">
  <img src="https://github.com/user-attachments/assets/b6e23225-fd1f-4971-ad00-729ec2bdef8f"
       alt="Static, normalized dashboard"
       width="100%" />
</td>
<td width="30%">
  <strong>Figure 3b: Squid Ink Prices with Anonymous Trades</strong><br/>
  <em>This plot filtered all anonymous trades to only show trades with quantity=15 as it was for early rounds. One could have looked out for those and early identified them during the rounds 1-4.</em>
</td>
</tr>
</table>

Our final strategy for Squid Ink focused purely on following this daily-extrema trading behavior, dynamically updating our positions based on detected trades and resetting when invalidations occurred. No active market making or mean reversion trading was used for this product. The result was a low-risk, high-reliability PnL contributor that did not rely on predicting price moves directly.

Anyone who carefully analyzed historical Prosperity 2 data or public write-ups — such as Stanford Cardinal’s or Jasper's — could have anticipated similar behaviors and prepared detection logic in advance. We also discovered and executed this strategy on another product in Prosperity 2 without having participated in Prosperity 1. Early identification of this behavior consistently netted us around 8,000 SeaShells per round, providing a stable and important edge in Round 1.

## Round 2

### Gift Baskets 🥀

In Round 2, three new individual products — Croissants, Jams, and Djembes — were introduced alongside two new baskets: PICNIC_BASKET1 and PICNIC_BASKET2.
Each basket represented a combination of different quantities of the three products, but crucially, it was not possible to directly convert baskets into their underlying constituents.
This setup clearly simulated a basic ETF (Exchange-Traded Fund) structure: linked assets that normally move together, but which might temporarily deviate, creating arbitrage opportunities.
In quantitative trading, finding and exploiting such linkages — when the synthetic price of a basket diverges from the sum of its parts — is a classic technique.

A deeper look revealed two main spread opportunities: first, trading the spread between the two baskets adjusted by Djembes (ETF1 - ETF2 + Djembes), and second, trading each basket relative to its synthetic value based on the underlying products (ETF - Constituents).
While both avenues were possible, we quickly identified that comparing baskets directly to their constituent sums was the stronger and more reliable path.

<table>
<tr valign="top">
<td width="70%">
  <img src="https://github.com/user-attachments/assets/9446a89f-fca0-4673-aec4-d65e09921129"
       alt="Dynamic dashboard"
       width="100%" />
</td>
<td width="30%">
  <strong>Figure 4: Basket Spreads over Time</strong><br/>
  <em>This plot shows the spreads (basket price - synthetic balue) for both baskets over time.</em>
</td>
</tr>
</table>

When approaching this kind of structure, it's crucial not to blindly apply textbook strategies but to first ask a fundamental question:
How could the market data have been generated?
The most natural generation process seemed to be that the three constituents' prices were independently randomized, and a mean-reverting noise sequence was then added on top to produce the basket price.
If that's true — and our early testing supported it — then the baskets were mean-reverting relative to their synthetic value, while the constituents themselves were not responding to the baskets.
Thus, it made sense to treat baskets as drifting toward their synthetic value, not the other way around.
Furthermore, while "hedging" by taking opposite positions in constituents could reduce variance, it would actually lower expected value slightly, especially when accounting for spread costs.

This understanding had important implications for strategy design.
Many teams might have rushed into using moving average crossovers or z-scores for trading signals — but applying such methods without a clear theoretical justification is dangerous.
For instance, a moving average crossover only makes sense if you believe there is a short-term trend overlaying a longer-term mean, which was not suggested by the structure here.
Similarly, using a z-score normalizes the spread by recent volatility, but unless volatility is known to vary meaningfully over time (which we did not observe here), this introduces unnecessary complexity and risk of overfitting.
It's easy to fall into the trap of throwing fancy techniques at the problem after a few hours of backtesting — but if you can't explain why a strategy should work from first principles, then any "outperformance" in historical data is probably noise.
From the beginning, we placed the highest value on building a deep structural understanding and keeping strategies simple, minimizing parameters whenever possible to maximize robustness.

Based on that philosophy, our final strategy was built around a fixed threshold model.
We entered long positions on the basket when the spread fell below a certain negative threshold, and short positions when it rose above a positive threshold.
Instead of dynamically scaling signals or chasing moving averages, we relied on fixed levels tuned through light grid search, focusing on robustness rather than maximizing historical PnL.
We further enhanced this base strategy by integrating an informed signal:
having already detected Olivia's trading behavior on Croissants (similar to Ink Squid), we used her inferred long/short position to bias our basket spread thresholds dynamically.
For example, if our base threshold was ±50, detecting Olivia as short would shift the long entry to -80 and the short entry to +20, dynamically tilting our bias in the favorable direction.
This cross-product adjustment allowed us to intelligently exploit correlations between Croissants and the baskets without overcomplicating the system.

<table>
<tr valign="top">
<td width="70%">
  <img src="https://github.com/user-attachments/assets/3b0f9a5d-e21e-41e3-82df-d96789ace379"
       alt="Dynamic dashboard"
       width="100%" />
</td>
<td width="30%">
  <strong>Figure 5: Optimal Parameter Search Grid</strong><br/>
  <em>These plots show backtesting basket pnls for each pair of parameters where the left plot corresponds to basket1 and the right one to basket2. num_param_1 corresponds to base thresholds, num_param_2 corresponds to the informed thresholds adjustments according to Olivia's position.</em>
</td>
</tr>
</table>

During parameter selection, we always prioritized landscape stability over pure performance peaks.
Rather than picking the best parameter set based on maximum backtested profit, we chose combinations that showed consistent, flat regions of good performance, reducing sensitivity to slight shifts and avoiding overfit disasters.
Additionally, because we noticed that the basket prices carried a slight persistent premium (the mean of the spread was not zero), we subtracted an estimated running premium from the spread during live trading, continuously updating it to prevent bias.

Also, for the final round, we were uncertain whether or not to fully hedge our basket exposure with the constituents.
Recognizing that any trading strategy can be viewed as a linear combination of two other strategies — in this case, fully hedged and fully unhedged — we decided to hedge 50% of our exposure as a balanced compromise.
Additionally, we adjusted our execution logic: instead of waiting for spreads to fully revert and cross opposite thresholds, we neutralized positions immediately upon spreads crossing zero (adjusted for the informed signal).
This change aimed to reduce variance and lock in profits more consistently, while maintaining approximately zero expected value under the assumption that spreads did not exhibit momentum when crossing zero.
It is important to note that here, "zero" still referred to the base threshold after incorporating informed adjustments.

Anyone thinking carefully about the problem — starting from generation assumptions, doing proper exploratory data analysis, and resisting the temptation to blindly overfit — could have arrived at a similar approach.
Concepts like synthetic replication, mean-reversion modeling (e.g., Ornstein-Uhlenbeck processes), and cross-product signal integration are core ideas in quantitative finance.
Through the base strategy, we achieved around 20,000–30,000 SeaShells per round trading baskets.
With the dynamic informed adjustment based on Croissants, that improved to 30,000–40,000 SeaShells per round, plus another 15,000 SeaShells per round directly from trading Croissants individually.


## Round 3

### Options 🧈

In Round 3, the competition introduced a new class of assets: Volcanic Rock Vouchers — effectively call options on a new underlying product, Volcanic Rock (VR).
There were five vouchers available, each with a distinct strike price — 9500, 9750, 10000, 10250, and 10500 — while the underlying Volcanic Rock itself traded around 10,000.
Each voucher granted the right (but not the obligation) to buy Volcanic Rock at the specified strike at expiry.
Importantly, options had limited time to live: starting with seven days until expiry in the first round, decreasing to just two days by the final round.
Without basic familiarity with options theory, particularly concepts like implied volatility and option pricing models, it would have been difficult to design strong strategies for this product.

#### IV Scalping 🧈

Our first major insight came from following hints dropped in the competition wiki, suggesting the construction of a volatility smile: plotting implied volatility (IV) against moneyness.
By fitting a parabola to the observed IVs across strikes and then detrending (subtracting the fitted curve from observed values), we could isolate IV deviations that were no longer dependent on moneyness.

<table>
<tr valign="top">
<td width="70%">
  <img src="https://github.com/user-attachments/assets/49be51d8-4335-4831-adb0-e811e50ce450"
       alt="Dynamic dashboard"
       width="100%" />
</td>
<td width="30%">
  <strong>Figure 6a: Volatility Smile</strong><br/>
  <em>This scatter plot visualizes implied volatility (v_t) vs moneyness (m_t) for different strikes. It also shows a fitted parabola to filter out noise and get v_hat_t for a given m_t essentially resembling the "fair" v_t given m_t. Outliers at the bottom left were disregarded as they referred to historical times where extrinsic value was too low.</em>
</td>
</tr>

<tr valign="top">
<td width="70%">
  <img src="https://github.com/user-attachments/assets/6aa60cbe-029d-49ed-b883-95c9b7e177df"
       alt="Static, normalized dashboard"
       width="100%" />
</td>
<td width="30%">
  <strong>Figure 6b: IV Deviations over Time</strong><br/>
  <em>This plot visualizes the deviations (v_t - v_hat_t) from 6a over time.</em>
</td>
</tr>
</table>

To convert these into actionable trading signals, we input the volatility-smile-implied IV into a Black-Scholes model to calculate a theoretical fair price, then compared it to the actual market price to find price deviations.
Plots of these price deviations — especially for the 10,000 strike call early on — revealed sharp short-term fluctuations, indicating scalping opportunities.

<table>
<tr valign="top">
<td width="70%">
  <img src="https://github.com/user-attachments/assets/ca6b1614-c6b2-4026-b41e-5af408fae69c"
       alt="Dynamic dashboard"
       width="100%" />
</td>
<td width="30%">
  <strong>Figure 6c: Price Deviations over Time</strong><br/>
  <em>This plot shows the deviations from 6b, just transformed into price space.</em>
</td>
</tr>
</table>

We initially focused on the 10,000 strike, but dynamically expanded to include other strikes as the underlying shifted and expiry approached, tracking profitability thresholds in real time to decide when to activate scalping on new options.
Statistical analysis, specifically testing for 1-lag negative autocorrelation in returns, strongly supported the existence of exploitable short-term inefficiencies across several strikes, further validating this approach.


<table>
<tr valign="top">
<td width="70%">
  <img src="https://github.com/user-attachments/assets/756d8dab-e76a-4ea6-a986-03d15d5f3bc3"
       alt="Dynamic dashboard"
       width="100%" />
</td>
<td width="30%">
  <strong>Figure 7a: 10k Call Price Fluctuations</strong><br/>
  <em>This plot shows the 10,000 call short term price fluctuations. The orange indicator refers to the theoretical call price using IV from the parabola (v_hat_t) given it's current moneyness.</em>
</td>
</tr>

<tr valign="top">
<td width="70%">
  <img src="https://github.com/user-attachments/assets/da9ae65a-b0a4-49e0-b072-b9abdbffad68"
       alt="Static, normalized dashboard"
       width="100%" />
</td>
<td width="30%">
  <strong>Figure 7b: 10k Call Price Fluctuations (normalized)</strong><br/>
  <em>This es the exact same plot as 7a, except prices were normalized by the orange indicator to make deviations - for visibility purposes - more stationary.</em>
</td>
</tr>
</table>

#### Mean Reversion Trading 🧈

Simultaneously, analysis of the underlying Volcanic Rock asset suggested potential mean reversion behavior.
Return distributions and price dynamics resembled Squid Ink, which was explicitly designed to mean revert in Round 1.
Autocorrelation analysis of Volcanic Rock returns, compared against randomized normal samples, confirmed significant short-term negative autocorrelation at various horizons, although caution was needed given the presence of large jumps and non-normal return distributions.
Given the limited historical data available (only three days), and uncertainty about future dynamics, fully committing to mean reversion was considered too risky.
Instead, we implemented a lightweight mean reversion model: tracking a fast rolling Exponential Moving Average (EMA) and trading deviations from this EMA using fixed thresholds — without scaling by rolling volatility — to keep the model simple and robust.

<table>
<tr valign="top">
<td width="70%">
  <img src="https://github.com/user-attachments/assets/ae8f01cf-9cd1-4867-ba26-dfcae781ccff"
       alt="Dynamic dashboard"
       width="100%" />
</td>
<td width="30%">
  <strong>Figure 8: Autocorrelation Plot for VR</strong><br/>
  <em>rolling autocorrelation of Volcanic Rock versus truly random sequences suggesting mean reversion behavior.</em>
</td>
</tr>
</table>

In the end, we deployed a hybrid strategy combining both alpha sources.
Our core focus remained on IV scalping, dynamically expanding across strikes and adjusting thresholds based on evolving conditions, while simultaneously maintaining a moderate mean reversion position — both in the underlying Volcanic Rock and in the deepest in-the-money call (the highest delta option available).
Importantly, this was not a delta hedge in the traditional sense: the delta exposure from scalping was relatively small, and explicit delta hedging would have been prohibitively expensive bid-ask spreads. It was rather a hedge against bad luck. Because this hybrid model was designed to minimize maximum regret across different possible market outcomes: it protected us if strong mean reversion materialized (even if other teams aggressively leveraged mean reversion delta exposure across multiple options and therefore outperforming us in a relative sense), while keeping our core reliance on the more stable, theory-supported scalping opportunities.

Someone could have arrived at a similar strategy without deep prior options expertise by carefully observing the market dynamics.
Even without constructing a full volatility smile, simply watching option prices — particularly the 10,000 strike — would reveal clear short-term mean-reversion patterns and negative autocorrelation in returns.
On the underlying asset side, basic return autocorrelation analysis and exploratory plotting would hint at mean reversion tendencies.
Thus, while a strong theoretical background was helpful, a combination of attentive observation, critical data analysis, and statistical common sense would have led to very similar conclusions.

In terms of results, IV scalping contributed approximately 150,000 SeaShells per round, providing strong and stable profits across all rounds. Mean reversion trading was much more volatile, delivering around 100,000, -30,000, and -20,000 SeaShells across the rounds respectively. Despite the swings, our hybrid approach allowed us to achieve consistently positive net results while keeping downside risks manageable.

Note: After the fourth round, where the mean reversion strategy resulted in a loss of approximately 30,000 SeaShells, we reassessed its validity. Although we no longer found strong empirical evidence to justify continuing with mean reversion purely on standalone expected value grounds, we knew that several top teams were actively only trading mean reversion strategies. So we figured, if they wouldn't find the IV scalping strategy, they might just accept the coinflip and go all in mean reversion because otherwise they would surely get overtaken by everyone. Facing a 200,000 SeaShell lead at that point, we made a calculated decision to maintain some mean reversion exposure — not because we believed it was necessarily positive EV anymore, but to hedge relatively against the teams still pursuing that angle. We estimated the 95% Value at Risk (VaR) of the mean reversion component to be around 50,000 SeaShells — only about 25% of our lead — leaving us with sufficient margin even if the strategy failed again. Under our assumptions, keeping this balanced exposure maximized our likelihood of securing first place by minimizing relative downside risk while preserving our core scalping profits. This turned out to be the right decision. Although, in the last round some random team very unnaturally jumped from 100+ rank to 1st place, we could keep a healthy distance to all teams that were previously close behind us. 



## Round 4
  
### Macarons

In Round 4, Magnificent Macarons, was introduced.
Their fictional value was described as depending on external factors like hours of sunlight, sugar prices, shipping costs, tariffs, and storage capacity.
Macarons could be traded on the local island exchange via a standard order book, or externally at fixed bid and ask prices, adjusted for im-/export and transportation fees.
The position limit for Macarons was 75 units, with a conversion limit of 10 units per timestep.
This setup opened up both straightforward arbitrage opportunities and, for those who studied the environment carefully, access to a much deeper hidden edge.

At first glance, the standard arbitrage logic applied: whenever the local bid exceeded the external ask (after fees), or the local ask was lower than the external bid, profitable conversions were possible.
However, there was a critical hidden detail: a taker bot existed that aggressively filled orders offered at attractive prices relative to a hidden "fair value."
Through experimentation, we discovered that offers priced at about int(externalBid + 0.5) would often get filled, even when no visible orderbook participants were present.
This taker bot executed approximately 60% of eligible trades, meaning that — in expectation — you could sell locally for a price about 3 SeaShells higher than the naive local best bid.
Over the course of 10,000 timesteps with a 10-unit conversion limit, this small price improvement could theoretically yield up to 300,000 SeaShells.
Of course, those conditions were not always present and realistic optimal profits were around 160,000 and 130,000 SeaShells across the two rounds. Still, the magnitude of this hidden edge made Macarons a very lucrative product of the competition.


<table>
<tr valign="top">
<td width="70%">
  <img src="https://github.com/user-attachments/assets/9985cdce-a23c-4f89-b288-7709160c1548"
       alt="Dynamic dashboard"
       width="100%" />
</td>
<td width="30%">
  <strong>Figure 9a: Macarons Microstructure</strong><br/>
  <em>This plot shows many (~60%) fills at a price better than local best bid. The orange indicator shows the external ask after costs (price for which we can convert negative inventory). It also shows that a straight forward local best bid to external ask arbitrage was currently not profitable.</em>
</td>
</tr>

<tr valign="top">
<td width="70%">
  <img src="https://github.com/user-attachments/assets/6822bdc7-1f44-4d43-9df3-289c6e7900a9"
       alt="Static, normalized dashboard"
       width="100%" />
</td>
<td width="30%">
  <strong>Figure 9b: Macarons Microstructure (normalized)</strong><br/>
  <em>This plot shows the same as 9a except it is normalized be the orange indicator (external ask after costs). It clearly demonstrates the price improvement versus local best bid. While in the snippet, the local best bid was unprofitable with about -1 SeaShell, we often got filled at a 2 SeaShell profitable opportunity.</em>
</td>
</tr>
</table>


Our final strategy focused on reliably exploiting this hidden arbitrage.
Each timestep, we placed limit sell orders for Macarons at precisely int(externalBid + 0.5), the maximum price that could still trigger fills from the taker bot.
We quoted only 10 units per timestep (the conversion limit), which meant we captured approximately 60% of the theoretical maximum profits, in line with the taker's acceptance probability.
In hindsight, quoting larger sizes (e.g., 20–30 units) would have allowed us to profitably convert surplus inventory even on non-fills, squeezing out closer to full optimal performance.
Nevertheless, even with conservative sizing, this strategy provided consistent, high-value returns with minimal risk.

Teams who prepared carefully had a clear advantage this round.
Similar hidden taker behavior had already appeared in Orchids during Prosperity 2, and public write-ups from top teams like Jasper and Linear Utility had discussed included it already.
Additionally, even without past experience, attentive teams could have detected the pattern by analyzing historical data: best asks occasionally priced close to best bid consistently getting filled was a clear signal.
Moreover, similar smart-taker behavior had appeared in assets like Rainforest Resin, providing further hints.
Thus, strong preparation, deep intuition about the Prosperity simulation, and diligent empirical observation were all key factors in unlocking the full potential of Macarons.
Those who recognized and exploited the hidden taker bot captured some of the highest single-product profits available in the entire competition.


     
## Round 5
  
In Round 5, no new products were introduced.
The main change was that historical trader IDs were made public, allowing teams to directly identify which trades were executed by specific bots.
For us, this did not fundamentally alter our strategies, as we had already identified Olivia’s behavior early in the competition.
However, we took this opportunity to update our detection logic: instead of inferring Olivia’s trades indirectly by tracking running minimums and maximums, we now simply checked the trader ID directly.
This adjustment helped eliminate false positives, reduced the risk of missing genuine Olivia trades, and saved a few hundred SeaShells over the course of the round.
As with every previous round, we also re-optimized all relevant parameters based on the latest available data to ensure robustness going into the final evaluation.

# Manual Challenge


# Frequently Asked Questions

## How to properly backtest? 
## What Price to use?
## How to break into quant trading?
## Discord useful?
## What else did we try?




