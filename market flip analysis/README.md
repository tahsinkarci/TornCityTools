# Torn City Item Market Flip Finder

Finds items on the Torn item market where the cheapest listings sit well below
the next price level. Buy the cheap stack, relist at (second lowest - 1), and keep the gap minus the 5% market fee.

The program **only reads** the market. The Torn API has no buy or sell endpoints,
and Torn's rules ban scripts that click on the website for you. It prints what to
buy, the price to list at, and a link to the item's market page. You buy and list it yourself.

## Setup

1. In Torn go to **Settings → API Keys** and create a **Limited Access** key
   (lets the program read your wallet). A Public key also works if you pass `--money`.
2. Start the app. The first time, it asks for your key and saves it in the
   `YOUR_TORN_API_KEY` user environment variable. The key is never written to a file.

You can also set the variable yourself:

```
setx YOUR_TORN_API_KEY "your-key-here"          # Windows (open a new terminal afterwards)
export YOUR_TORN_API_KEY="your-key-here"        # macOS / Linux (add to your shell profile)
```

Optionally copy `config.example.json` to `config.json` to change the default settings.

## Terms of use for your API key

| | |
|---|---|
| **Data storage** | Only on your computer: the item list (`items_cache.json`), market snapshots (`market_history.json`) and your settings (`config.json`). Your balance is not saved. |
| **Data sharing** | None. Data goes only between your computer and `api.torn.com`. |
| **Purpose of use** | Find item market flips and show your spendable cash. Read-only. |
| **Key storage & sharing** | Saved in the `YOUR_TORN_API_KEY` user environment variable on your computer. Never written to a file or sent anywhere except Torn. |
| **Key access level** | Limited Access (to read your balance). Public works if you set the money amount yourself. |

## Fair use of the Torn API

- Uses only the official API (`api.torn.com`). It never loads or reads torn.com pages,
  and opens the market page in your browser only when you click to do so.
- Makes at most one call every 0.7 s (about 85 per minute) across the whole program,
  below Torn's limit of 100 per minute. Don't run the command line and window app
  at the same time, as the limit is shared across all your keys.
- Stops at once if the key is wrong, paused or disabled, or if Torn blocks or limits requests,
  instead of retrying.

## Window app (Tkinter)

Double-click `torn_flipper_gui.pyw`, or run `python torn_flipper_gui.py`.

1. On first launch, paste your API key and click **Save** (stored in `YOUR_TORN_API_KEY`).
   To change it later, open **Settings**.
2. Add items to the **Watchlist** on the left, then click **Check watchlist**,
   or click **Scan market** to check the top N most valuable items.
3. Green rows are flips worth doing. Click a column heading to sort.
4. Click a row to see the suggestion. Double-click it, or use **Open market page**,
   to buy in Torn. **Copy sell price** puts the listing price on your clipboard.
5. Tick **Auto-refresh** to keep updating. Repeated updates also measure liquidity.

## Command line

```
python torn_flipper.py check Xanax "Feathery Hotel Coupon"   # specific items
python torn_flipper.py check                                 # items in your watchlist
python torn_flipper.py check --watch 120                     # refresh every 2 min
python torn_flipper.py scan --max-items 200                  # 200 most valuable items
python torn_flipper.py scan --csv results.csv                # full scan (~10+ min)
python torn_flipper.py check Xanax --money 5000000           # set your budget yourself
```

## What it shows

| Column | Meaning |
|---|---|
| Lowest / Qty | Cheapest price and how many units are listed at it |
| Cost all | Money needed to buy that whole stack |
| 2nd low | Next price level up |
| Sell at | 2nd lowest - 1, your listing price |
| Profit all | (Sell at x 0.95 - Lowest) x Qty |
| Can buy / Your profit | Limited by the cash in your wallet |
| Liquidity | How fast the item sells (see below) |

**Liquidity:** each run saves a snapshot to `market_history.json`. When listings
disappear between snapshots, they count as sales, giving units per hour.
"Fast" means your stack should sell within about 6 hours, "medium" within 2 days.
Delisted items also count as sales, so this is an upper estimate.
Until there are a few snapshots (use `--watch`), the program guesses from how many listings there are, marked with `*`.

Settings like minimum profit, ROI, fee and skipped item types are in `config.json`.
