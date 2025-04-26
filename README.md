# Frankfurt Hedgehogs 📈

This writeup shares our algorithm and insights that brought us to 2nd place globally in IMC Prosperity 3 (2025). Outperforming (almost) all other 12,000+ teams, we achieved a final score of 1,433,876 SeaShells but unfortunately we didn't win the 10,000$ prize for it as we had already earned prize money in last year's competition. :)

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

text

  <img src="https://github.com/user-attachments/assets/54363d35-63ac-406f-b2de-ad6a06e7433d"
       alt="Dynamic dashboard"
       width="70%" />

text

### Kelp ⭐

text

  <img src="https://github.com/user-attachments/assets/2a7c36dc-76b8-482d-934b-c9ee7ff527f6"
       alt="Dynamic dashboard"
       width="70%" />

  <img src="https://github.com/user-attachments/assets/80b5f2cb-ae7a-400b-aff0-311e977c2d58"
       alt="Static, normalized dashboard"
       width="70%" />

text

<img width="744" alt="Screenshot 2024-05-20 at 11 54 46 PM" src="https://github.com/ericcccsliu/imc-prosperity-2/assets/62641231/26d2f65c-2a5a-4252-8094-34a35a280020">
<p align="center">
  <em>histograms of volumes on the first and second level of the bid side</em>
</p>

text

### Squid Ink ⭐

text

  <img src="https://github.com/user-attachments/assets/9f552b07-98e9-4488-b4b9-95b2e1435747"
       alt="Dynamic dashboard"
       width="70%" />

  <img src="https://github.com/user-attachments/assets/b6e23225-fd1f-4971-ad00-729ec2bdef8f"
       alt="Dynamic dashboard"
       width="70%" />


text

## Round 2

### Gift Baskets 🥀

text

<img src="https://github.com/user-attachments/assets/9446a89f-fca0-4673-aec4-d65e09921129"
     alt="Dynamic dashboard"
     width="70%" />

<img src="https://github.com/user-attachments/assets/3b0f9a5d-e21e-41e3-82df-d96789ace379"
     alt="Dynamic dashboard"
     width="70%" />

text

## Round 3

### Options 🧈

text

#### IV Scalping 🧈
<img src="https://github.com/user-attachments/assets/49be51d8-4335-4831-adb0-e811e50ce450"
     alt="Dynamic dashboard"
     width="70%" />

<img src="https://github.com/user-attachments/assets/6aa60cbe-029d-49ed-b883-95c9b7e177df"
     alt="Dynamic dashboard"
     width="70%" />

<img src="https://github.com/user-attachments/assets/ca6b1614-c6b2-4026-b41e-5af408fae69c"
     alt="Dynamic dashboard"
     width="70%" />

<img src="https://github.com/user-attachments/assets/756d8dab-e76a-4ea6-a986-03d15d5f3bc3"
     alt="Dynamic dashboard"
     width="70%" />
     
<img src="https://github.com/user-attachments/assets/da9ae65a-b0a4-49e0-b072-b9abdbffad68"
     alt="Dynamic dashboard"
     width="70%" />

#### Mean Reversion Trading 🧈

<img src="https://github.com/user-attachments/assets/ae8f01cf-9cd1-4867-ba26-dfcae781ccff"
     alt="Dynamic dashboard"
     width="70%" />

text

## Round 4
  
### Macarons

text

<img src="https://github.com/user-attachments/assets/9985cdce-a23c-4f89-b288-7709160c1548"
     alt="Dynamic dashboard"
     width="70%" />

<img src="https://github.com/user-attachments/assets/6822bdc7-1f44-4d43-9df3-289c6e7900a9"
     alt="Dynamic dashboard"
     width="70%" />
     
text

## Round 5
  
### Macarons

text



# Manual Challenge


# Frequently Asked Questions

## How to properly backtest? 
## What Price to use?
## How to break into quant trading?
## Discord useful?
## What else did we try?




