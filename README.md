# Frankfurt Hedgehogs 📈

This repository contains research and algorithms for our team, Linear Utility, in IMC Prosperity 2024. We placed 2nd globally, with an overall score of 3,501,647 seashells, and took home $10,000 in prize money. 

## the team ✨


<table width="50%">
  <tbody>
    <tr>
      <td align="center" valign="top" width="150px">
        <a href="https://www.linkedin.com/in/timo-diehm">
          <img src="https://github.com/user-attachments/assets/29c05872-f107-4bb2-82bd-961865f8cba3" width="100px;" alt="Timo Diehm"/>
          <br />
          <p><b>Timo Diehm</b></p></a>
      </td>
      <td align="center" valign="top" width="150px">
        <a href="https://www.linkedin.com/in/arne-witt">
          <img src="https://github.com/user-attachments/assets/61ee7433-469e-4a47-9bf6-a203aea6a0d5" width="100px;" alt="Arne Witt"/>
          <br />
          <p><b>Arne Witt</b></p></a>
      </td>
      <td align="center" valign="top" width="150px">
        <a href="https://www.linkedin.com/in/marvin-schuster">
          <img src="https://github.com/user-attachments/assets/61ee7433-469e-4a47-9bf6-a203aea6a0d5" width="100px;" alt="Marvin Schuster"/>
          <br />
          <p><b>Marvin Schuster</b></p></a>
      </td>
    </tr>
  </tbody>
</table>


## the competition 🏆


IMC Prosperity 2024 was an algorithmic trading competition that lasted over 15 days, with over 9000 teams participating globally. In the challenge, we were tasked with algorithmically trading various products, such as amethysts, starfruit, orchids, coconuts, and more, with the goal of maximizing seashells: the underlying currency of our island. We started trading amethysts and starfruit in round 1, and with each subsequent round, more products were added. At the end of each round, our trading algorithm was evaluated against bot participants in the marketplace, whose behavior we could try and predict through historical data. The PNL from this independent evaluation would then be compared against all other teams. 

In addition to the main algorithmic trading focus, the competition also consisted of manual trading challenges in each round. The focus of these varied widely, and in the end, manual trading accounted for just a small fraction of our PNL. 

For documentation on the algorithmic trading environment, and more context about the competition, feel free to consult the [Prosperity 2 Wiki](https://imc-prosperity.notion.site/Prosperity-2-Wiki-fe650c0292ae4cdb94714a3f5aa74c85). 

## organization 📂

This repository contains all of our code–including internal tools, research notebooks, raw data and backtesting logs, and all versions of our algorithmic trader. The repository is organized by round. Our backtester mostly remained unchanged from round 1, but we simply copied its files over to each subsequent round, so you'll find a version of that in each folder. Within each round, you can locate the algorithmic trading code we used in our final submission by looking for the latest version–for example, for round 1, we used [`round_1_v6.py`](https://github.com/ericcccsliu/imc-prosperity-2/blob/main/round1/round_1_v6.py) for our final submission. Our visualization dashboard is located in the `dashboard` folder. 

<details>
<summary><h2>tools 🛠️</h2></summary>

Instead of relying heavily on open-source tools, which many successful teams did, we decided instead to build our tools in-house. This gave us the ability to tailor our tools heavily to our own needs. We built two main tools: a backtester and a visualization dashboard. 

### backtester 🔙

We realized we needed a comprehensive backtesting environment very early on. Our backtester was built to take in historical data and a trading algorithm. With the historical data, it would construct all the necessary information (replicating the actual trading environment perfectly) that our trading algorithm needed, input it into our trading algorithm, and receive the orders that our algorithm would send. Then, it would match those orders to the orderbook to generate trades. In order to simulate market making, we would also look at trades between bots at each iteration. If there was a trade between bots at a price worse than our own quotes, we'd attribute the trade to ourselves. After running, our backtester would create a log file in the exact same format as the Prosperity website. 

Because we often found ourselves backtesting over various parameters to find the best combination, we also modified our trader class to optionally take in trading parameters as a dictionary upon instantiation. This allowed us to gridsearch over all possible parameters in backtesting, allowing us to quickly optimize our ideas. 

### dashboard 💨

The dashboard we developed helped us a lot during the early rounds in pnl generation, allowing us to develop new alpha and also optimize our alphas by finding desirable trades our algorithm didn't do or undesirable trades that our algorithm did. One extremely helpful feature we developed was a syncing functionality, where clicking on a graph (or entering a specific timestamp manually) would synchronize all visualizations to that timestamp, allowing us to explore local anomalies in depth. 


![dashboard explanation](https://github.com/user-attachments/assets/6c283b73-07e3-4b3a-b8b5-9b38cc51b314)
<p align="center">
  <em>we used to have actual section headers, but at some point we (Jerry and Eric) got hungry and started editing them</em>
</p>

</details>
<details>
<summary><h2>round 1️⃣</h2></summary>

In round 1, we had access to two symbols to trade: amethysts and starfruit. 

### Rainforest Resin 🔮
Amethysts were fairly simple, as the fair price clearly never deviated from 10,000. As such, we wrote our algorithm to trade against bids above 10,000 and asks below 10,000. Besides taking orders, our algorithm also would market-make, placing bids and asks below and above 10,000, respectively, with a certain edge. Using our backtester, we gridsearched over several different values to find the most profitable edge to request. This worked well, getting us about 16k seashells over backtests

  <img src="https://github.com/user-attachments/assets/54363d35-63ac-406f-b2de-ad6a06e7433d"
       alt="Dynamic dashboard"
       width="70%" />

However, through looking at backtest logs in our dashapp, we discovered that many profitable trades were prevented by our position limits, as we were unable to long or short more than 20 amethysts (and starfruit) at any given moment. To fix this issue, we implemented a strategy to clear our position–our algorithm would do 0 ev trades, if available, just to get our position closer to 0, so that we'd be able to do more positive ev trades later on. This strategy bumped our pnl up by about 3%. 

### Kelp ⭐
Finding a good fair price for starfruit was tougher, as its price wasn't fixed–it would slowly randomwalk around. Nonetheless, we observed that the price was relatively stable locally. So we created a fair using a rolling average of the mid price over the last *n* timestamps, where *n* was a parameter which we could optimize over in backtests[^1]. Market-making, taking, and clearing (the same strategies we did with amethysts) worked quite well around this fair value. 

  <img src="https://github.com/user-attachments/assets/2a7c36dc-76b8-482d-934b-c9ee7ff527f6"
       alt="Dynamic dashboard"
       width="70%" />

  <img src="https://github.com/user-attachments/assets/80b5f2cb-ae7a-400b-aff0-311e977c2d58"
       alt="Static, normalized dashboard"
       width="70%" />


However, using the mid price–even in averaging over it–didn't seem to be the best, as the mid price was noisy from market participants continually putting orders past mid (orders that we thought were good to fair and therefore ones that we wanted to trade against). Looking at the orderbook, we found out that, at all times, there was a market making bot quoting relatively large sizes on both sides, at prices that were unaffected by smaller participants[^2]. Using this market maker's mid price as a fair turned out to be much less noisy and generated more pnl in backtests. 

<img width="744" alt="Screenshot 2024-05-20 at 11 54 46 PM" src="https://github.com/ericcccsliu/imc-prosperity-2/assets/62641231/26d2f65c-2a5a-4252-8094-34a35a280020">
<p align="center">
  <em>histograms of volumes on the first and second level of the bid side</em>
</p>

Surprisingly, when we tested our algorithm on the website, we figured out that the website was marking our pnl to the market maker's mid instead of the actual mid price. We were able to verify this by backtesting a trading algorithm that bought 1 starfruit in the first timestamp and simply held it to the end–our pnl graph marked to market maker mid in our own backtesting environment exactly replicated the pnl graph on the website. This boosted our confidence in using the market maker mid as fair, as we realized that we'd just captured the true internal fair of the game. Besides this, some research on the fair price showed that starfruit was very slightly mean reverting[^3], and the rest was very similar to amethysts, where we took orders and quoted orders with a certain edge, optimizing all parameters in our internal backtester with a grid search.

### Squid Ink ⭐
Finding a good fair price for starfruit was tougher, as its price wasn't fixed–it would slowly randomwalk around. Nonetheless, we observed that the price was relatively stable locally. So we created a fair using a rolling average of the mid price over the last *n* timestamps, where *n* was a parameter which we could optimize over in backtests[^1]. Market-making, taking, and clearing (the same strategies we did with amethysts) worked quite well around this fair value. 

  <img src="https://github.com/user-attachments/assets/9f552b07-98e9-4488-b4b9-95b2e1435747"
       alt="Dynamic dashboard"
       width="70%" />

  <img src="https://github.com/user-attachments/assets/b6e23225-fd1f-4971-ad00-729ec2bdef8f"
       alt="Dynamic dashboard"
       width="70%" />


After round 1, our team was ranked #3 in the world overall. We had an algo trading profit of 34,498 seashells–just 86 seashells behind first place.

</details>

<details>
<summary><h2>round 2️⃣</h2></summary>
  
### Gift Baskets 🥀

Orchids were introduced in round 2, as well as a bunch of data on sunlight, humidity, import/export tariffs, and shipping costs. The premise was that orchids were grown on a separate island[^4], and had to be imported–subject to import tariffs and shipping costs, and that they would degrade with suboptimal levels of sunlight and humidity. We were able to trade orchids both in a market on our own island, as well as through importing them from the South archipelago. With this, we had two initial approaches. The obvious approach, to us, was to look for alpha in all the data available, investigating if the price of orchids could be predicted using sunlight, humidity, etc. The other approach involved understanding exactly how the mechanisms for trading orchids worked, as the documentation was fairly unclear. Thus, we split up: Eric looked for alpha in the historical data while Jerry worked on understanding the actual trading environment.

<img src="https://github.com/user-attachments/assets/9446a89f-fca0-4673-aec4-d65e09921129"
     alt="Dynamic dashboard"
     width="70%" />

<img src="https://github.com/user-attachments/assets/3b0f9a5d-e21e-41e3-82df-d96789ace379"
     alt="Dynamic dashboard"
     width="70%" />


</details>
<details>
<summary><h2>round 3️⃣</h2></summary>
Gift baskets :basket:, chocolate 🍫, roses 🌹, and strawberries 🍓 were introduced in round 3, where a gift basket consisted of 4 chocolate bars, 6 strawberries, and a single rose. This round, we mainly traded spreads, which we defined as `basket - synthetic`, with `synthetic` being the sum of the price of all products in a basket.

### Options 🧈
In this round, we quickly converged on two hypotheses. The first hypothesis was that the synthetic would be leading baskets or vice versa, where changes in the price of one would lead to later changes in the price of the other.  Our second hypothesis was that the spread might simply just be mean reverting. We observed that the price of the spread–which theoretically should be 0–hovered around some fixed value, which we could trade around. We looked into leading/lagging relationships between the synthetic and the basket, but this wasn't very fruitful, so we then investigated the spread price. 

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


After results from this round were released, we found that our actual pnl had a significant amount of slippage compared to our backtests–we made only 111k seashells from our algo. Nevertheless, we got a bit lucky–all the teams ahead of us in this round seemed to overfit significantly more, as we were ranked #2 overall.

</details>
<details>
<summary><h2>round 4️⃣</h2></summary>
  
### Macarons
Coconuts and coconut coupons were introduced in round 4. Coconut coupons were the 10,000 strike call option on coconuts, with a time to expiry of 250 days. The price of coconuts hovered around 10,000, so this option was near-the-money. 

This round was fairly simple. Using Black-Scholes, we calculated the implied volatility of the option, and once we plotted this out, it became clear that the implied vol oscillated around a value of ~16%. We implemented a mean reverting strategy similar to round 3, and calculated the delta of the coconut coupons at each time in order to hedge with coconuts and gain pure exposure to vol. However, the delta was around 0.53 while the position limits for coconuts/coconut coupons were 300/600, respectively. This meant that we couldn't be fully hedged when holding 600 coupons (we would be holding 18 delta). Since the coupon was far away from expiry (thus, gamma didn't matter as much) and holding delta with vega was still positive ev (but higher var), we ran the variance in hopes of making more from our exposure to vol. 


<img src="https://github.com/user-attachments/assets/9985cdce-a23c-4f89-b288-7709160c1548"
     alt="Dynamic dashboard"
     width="70%" />

<img src="https://github.com/user-attachments/assets/6822bdc7-1f44-4d43-9df3-289c6e7900a9"
     alt="Dynamic dashboard"
     width="70%" />

