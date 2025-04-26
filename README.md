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

After countless requests, we decided to share our final algorithm along with all of our insights to give back to the Prosperity 3 community.
We realize that fellow or future participants have varying levels of experience with quant and algorithmic trading, so we tried to make this write-up as detailed and accessible as possible. Some topics are just too deep to explain in a short paragraph, so we included links to external resources that less experienced readers should carefully study.

<br/>

This report goes far beyond just presenting our final strategies.
We not only break down those strategies and insights that worked for us, but also share the thought processes and decisions behind them.
That said, this document is mainly intended for fellow or future Prosperity participants, since it focuses specifically on Prosperity 3.
If you're more interested in how we consistently stayed at the top across multiple competitions — and want general advice on how to compete against thousands of teams — check out our separate blog post:
<br />
<a href="https://www.linkedin.com/in/timo-diehm">How to (Almost) Win Against Thousands of Other Teams (link). </a>

## the competition 🏆

IMC Prosperity 3 (2025) was an algorithmic trading competition that lasted over 5 rounds and 15 days, with over 12,000 teams participating globally. In the challenge, we were tasked with algorithmically trading various products - simulating various real world trading opportunities such as market making, statistical arbitrage, scalping, locational arbitrage etc. - with the goal of maximizing profits. All of it was very well gamified such that each team acted as a different island that traded products like Kelp, Squid Ink, Picnic Baskets (ETF) or Volcanic Rock Vouchers (Options) and the currency was seashells. It started off with only three products in the first round and progressively increased to 15 products for the last round. At the end of each round, our updated trading algorithm was evaluated against bot participants in the marketplace, whose behavior or pattern (in or between) prices we could try to predict and optimize for through historical data. The PNL from this independent evaluation would then be compared against all other teams.

In addition to the main algorithmic trading focus, the competition also consisted of manual trading challenges in each round. Although, accounting for just a small fraction of total PNL, those challenges were fun as they incorporated optimization under uncertainty under aspects of game theory or other fun challenges such as news trading.

For documentation on the algorithmic trading environment, and more context about the competition, feel free to consult the Prosperity 3 Wiki. [LINK]

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

text

### backtester 🔙

text

### dashboard 💨

text

![dashboard explanation](https://github.com/user-attachments/assets/6c283b73-07e3-4b3a-b8b5-9b38cc51b314)
<p align="center">
  <em>we used to have actual section headers, but at some point we (Jerry and Eric) got hungry and started editing them</em>
</p>

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




