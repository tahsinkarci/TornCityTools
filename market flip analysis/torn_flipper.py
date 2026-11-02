#!/usr/bin/env python3
"""
Torn City item market flip finder.

Reads the item market through the official Torn API v2 (read-only) and looks for
items where the cheapest listings are well below the next price level. Buying
the cheapest stack and relisting at (second lowest - 1) can then be profitable.

The Torn API cannot buy or sell. Torn's rules also forbid automating clicks on
the website, so this program only makes suggestions and gives you a link to the
market page. You make the purchase yourself.

Usage:
  python torn_flipper.py check "Xanax" "Feathery Hotel Coupon"
  python torn_flipper.py check            (uses the watchlist in config.json)
  python torn_flipper.py scan             (scans all tradable items, slow)
  python torn_flipper.py check --watch 120   (repeat every 120 s, measures liquidity)

Standard library only - no pip install needed.
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.torn.com/v2"
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
ITEMS_CACHE_PATH = os.path.join(HERE, "items_cache.json")
HISTORY_PATH = os.path.join(HERE, "market_history.json")
MARKET_LINK = "https://www.torn.com/page.php?sid=ItemMarket#/market/view=search&itemID={id}"
API_KEY_ENV = "YOUR_TORN_API_KEY"  # the API key lives only in this environment variable

DEFAULT_CONFIG = {
    "fee_percent": 5.0,          # Torn item market sales tax (5% since June 2025)
    "min_profit": 10000,         # hide flips that make less than this (whole stack)
    "min_roi_percent": 2.0,      # hide flips with lower return per unit
    "request_delay": 0.7,        # seconds between API calls (Torn limit: 100/min)
    "skip_types": ["Weapon", "Armor"],  # unique items, price gaps there are misleading
    "min_market_price": 1000,    # scan mode: skip cheap junk items
    "watchlist": [],             # item names or ids used by "check" with no args
    "money_source": "wallet",    # wallet | wallet_vault | all_cash (see MONEY_SOURCES)
}

MAX_SNAPSHOTS = 60  # per item, for liquidity estimates


# --------------------------------------------------------------------------- API

class TornAPIError(Exception):
    pass


class TornClient:
    def __init__(self, api_key, delay):
        self.api_key = api_key
        self.delay = delay
        self._last_call = 0.0
        self.calls = 0

    def get(self, path, **params):
        params = {k: v for k, v in params.items() if v is not None}
        url = API_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)

        for attempt in range(3):
            wait = self.delay - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(url, headers={
                "Authorization": f"ApiKey {self.api_key}",
                "User-Agent": "torn-flip-finder/1.0",
            })
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.load(resp)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                self._last_call = time.monotonic()
                if attempt == 2:
                    raise TornAPIError(f"Network error on {path}: {e}")
                time.sleep(3)
                continue
            finally:
                self.calls += 1
            self._last_call = time.monotonic()

            err = data.get("error") if isinstance(data, dict) else None
            if err:
                code = err.get("code")
                if code == 5 and attempt < 2:  # too many requests
                    print("  Rate limited by Torn, waiting 60 s...", file=sys.stderr)
                    time.sleep(60)
                    continue
                raise TornAPIError(f"Torn API error {code}: {err.get('error')} ({path})")
            return data
        raise TornAPIError(f"Gave up on {path}")

    def items(self):
        return self.get("/torn/items")["items"]

    def item_market(self, item_id):
        return self.get(f"/market/{item_id}/itemmarket", limit=100)["itemmarket"]

    def money(self):
        """Your balances. Needs a Limited Access key."""
        try:
            return self.get("/user/money")["money"]
        except TornAPIError as e:
            if "error 16" in str(e):
                raise TornAPIError("Your API key can't read balances. Create a Limited Access key "
                                   "in Torn (Settings > API Keys).")
            raise

    def wallet(self):
        return self.money()["wallet"]


# Which balances count as "money to spend". Item market purchases are paid from
# your wallet, so for the other sources you withdraw the cash before buying.
MONEY_SOURCES = {
    "wallet": "Wallet (cash on hand)",
    "wallet_vault": "Wallet + property vault",
    "all_cash": "Wallet + vault + Cayman + faction",
}


def balance_parts(m):
    """Break /user/money into named amounts (city bank is locked, so it is left out)."""
    faction = m.get("faction") or {}
    return {
        "wallet": m.get("wallet") or 0,
        "vault": m.get("vault") or 0,
        "cayman": m.get("cayman_bank") or 0,
        "faction": faction.get("money") or 0,
    }


def spendable(m, source):
    p = balance_parts(m)
    if source == "wallet_vault":
        return p["wallet"] + p["vault"]
    if source == "all_cash":
        return p["wallet"] + p["vault"] + p["cayman"] + p["faction"]
    return p["wallet"]


# ---------------------------------------------------------------- local storage

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def read_user_env_windows(name):
    """Read a user environment variable straight from the registry (Windows only).

    Picks up a key saved after this process (or its parent shell) started.
    """
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, name)[0]
    except (ImportError, OSError):
        return ""


def get_api_key():
    """The API key comes only from the YOUR_TORN_API_KEY environment variable."""
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key and os.name == "nt":
        key = (read_user_env_windows(API_KEY_ENV) or "").strip()
        if key:
            os.environ[API_KEY_ENV] = key
    return key


def set_api_key(key):
    """Store the key in YOUR_TORN_API_KEY for this run and, on Windows, permanently
    for the current user. Returns True if it was saved permanently."""
    os.environ[API_KEY_ENV] = key
    if os.name != "nt":
        return False
    try:
        import ctypes
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, API_KEY_ENV, 0, winreg.REG_SZ, key)
        # Tell Windows the environment changed so newly started programs see it.
        HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", SMTO_ABORTIFHUNG, 2000, None)
        return True
    except (ImportError, OSError):
        return False


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(load_json(CONFIG_PATH, {}))
    cfg["api_key"] = get_api_key()  # never taken from config.json
    return cfg


def save_config(cfg):
    """Save settings to config.json. The API key is never written to disk here."""
    save_json(CONFIG_PATH, {k: v for k, v in cfg.items() if k != "api_key"})


def load_items(client, max_age_hours=24):
    cache = load_json(ITEMS_CACHE_PATH, None)
    if cache and time.time() - cache.get("saved_at", 0) < max_age_hours * 3600:
        return cache["items"]
    print("Downloading item catalog...", file=sys.stderr)
    items = client.items()
    save_json(ITEMS_CACHE_PATH, {"saved_at": time.time(), "items": items})
    return items


def find_item(items, query):
    if str(query).isdigit():
        for it in items:
            if it["id"] == int(query):
                return it
        raise SystemExit(f"No item with id {query}")
    q = query.lower().strip()
    exact = [it for it in items if it["name"].lower() == q]
    if exact:
        return exact[0]
    partial = [it for it in items if q in it["name"].lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise SystemExit(f"No item matches '{query}'")
    names = ", ".join(it["name"] for it in partial[:10])
    raise SystemExit(f"'{query}' matches several items: {names}. Be more specific.")


# ------------------------------------------------------------------- liquidity

def record_snapshot(history, item_id, cache_ts, levels):
    snaps = history.setdefault(str(item_id), [])
    if snaps and snaps[-1]["t"] == cache_ts:
        return  # same cached data as last time, nothing new
    snaps.append({"t": cache_ts, "levels": {str(p): a for p, a in levels}})
    del snaps[:-MAX_SNAPSHOTS]


def sales_per_hour(snaps):
    """Estimate units sold per hour from listings that disappeared between snapshots.

    Only prices inside the newer snapshot's visible window count, so listings
    pushed past the 100-listing limit are not mistaken for sales. Delisted items
    also count as "sold", so treat this as an upper estimate.
    """
    if len(snaps) < 2:
        return None
    hours = (snaps[-1]["t"] - snaps[0]["t"]) / 3600
    if hours < 0.05:  # need at least ~3 minutes of data
        return None
    sold = 0
    for older, newer in zip(snaps, snaps[1:]):
        cur = newer["levels"]
        if not cur:
            continue
        max_visible = max(int(p) for p in cur)
        for p, amt in older["levels"].items():
            if int(p) <= max_visible:
                sold += max(0, amt - cur.get(p, 0))
    return sold / hours


def liquidity_label(rate, qty, listing_count):
    if rate is None:
        # No history yet: fall back to how busy the order book looks.
        if listing_count >= 60:
            return "busy book*"
        if listing_count >= 15:
            return "some sellers*"
        return "thin book*"
    if rate <= 0:
        return "no sales seen"
    hours_to_sell = qty / rate
    if hours_to_sell <= 6:
        speed = "fast"
    elif hours_to_sell <= 48:
        speed = "medium"
    else:
        speed = "slow"
    return f"{speed} ({rate:.1f}/h)"


# -------------------------------------------------------------------- analysis

def price_levels(listings):
    levels = {}
    for lst in listings:
        levels[lst["price"]] = levels.get(lst["price"], 0) + lst["amount"]
    return sorted(levels.items())


def analyze(item, market, wallet, fee_pct, history):
    levels = price_levels(market["listings"])
    record_snapshot(history, item["id"], market.get("cache_timestamp", int(time.time())), levels)

    result = {
        "id": item["id"],
        "name": item["name"],
        "avg_price": market["item"].get("average_price") or 0,
        "listings": len(market["listings"]),
        "levels": levels[:10],  # cheapest price levels, for the order book view
        "ok": False,
    }
    if len(levels) < 2:
        result["note"] = "fewer than two price levels listed"
        return result

    (low, qty), (second, second_qty) = levels[0], levels[1]
    sell_at = second - 1
    net_per_unit = int(sell_at * (1 - fee_pct / 100)) - low
    can_buy = min(qty, wallet // low) if wallet is not None and low > 0 else qty
    rate = sales_per_hour(history.get(str(item["id"]), []))

    warnings = []
    avg = result["avg_price"]
    if avg and sell_at > avg * 1.25:
        warnings.append(f"sell price is {sell_at / avg - 1:.0%} above the average sale price "
                        f"(${avg:,}), may not sell quickly")
    if wallet is not None and can_buy < qty:
        warnings.append(f"you can only afford {can_buy} of {qty}")

    result.update({
        "ok": True,
        "low": low,
        "qty": qty,
        "cost_all": low * qty,
        "second": second,
        "second_qty": second_qty,
        "sell_at": sell_at,
        "gap_pct": (second - low) / low * 100 if low else 0,
        "net_per_unit": net_per_unit,
        "profit_all": net_per_unit * qty,
        "roi_pct": net_per_unit / low * 100 if low else 0,
        "can_buy": can_buy,
        "cost_yours": low * can_buy,
        "profit_yours": net_per_unit * can_buy,
        "liquidity": liquidity_label(rate, qty, result["listings"]),
        "warnings": warnings,
    })
    return result


def is_opportunity(r, min_profit, min_roi):
    return (r["ok"] and r["can_buy"] > 0 and r["net_per_unit"] > 0
            and r["profit_yours"] >= min_profit and r["roi_pct"] >= min_roi)


# ---------------------------------------------------------------------- output

def money(n):
    return f"-${-n:,}" if n < 0 else f"${n:,}"


def print_table(results):
    rows = [r for r in results if r["ok"]]
    if not rows:
        return
    head = ["Item", "Lowest", "Qty", "Cost all", "2nd low", "Sell at", "Gap",
            "Profit all", "ROI", "Can buy", "Your profit", "Liquidity"]
    body = [[r["name"][:24], money(r["low"]), str(r["qty"]), money(r["cost_all"]),
             money(r["second"]), money(r["sell_at"]), f"{r['gap_pct']:.1f}%",
             money(r["profit_all"]), f"{r['roi_pct']:.1f}%", str(r["can_buy"]),
             money(r["profit_yours"]), r["liquidity"]] for r in rows]
    widths = [max(len(x) for x in col) for col in zip(head, *body)]
    line = "  ".join(h.ljust(w) for h, w in zip(head, widths))
    print(line)
    print("-" * len(line))
    for row in body:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)))


def format_suggestion(r, fee_pct):
    if not r["ok"]:
        return f"{r['name']} (#{r['id']})\n  {r['note']}\n  Market link      : {MARKET_LINK.format(id=r['id'])}"
    lines = [
        f"{r['name']} (#{r['id']})",
        f"  Lowest price     : {money(r['low'])} x {r['qty']}  ->  {money(r['cost_all'])} to buy all",
        f"  Second lowest    : {money(r['second'])} x {r['second_qty']}",
        f"  List yours at    : {money(r['sell_at'])}  (you keep "
        f"{money(int(r['sell_at'] * (1 - fee_pct / 100)))} after {fee_pct:g}% fee)",
        f"  Profit per unit  : {money(r['net_per_unit'])}  ({r['roi_pct']:.1f}% ROI)",
        f"  Profit if all    : {money(r['profit_all'])}",
    ]
    if r["can_buy"] != r["qty"]:
        lines.append(f"  You can afford   : {r['can_buy']} units  ->  cost {money(r['cost_yours'])}, "
                     f"profit {money(r['profit_yours'])}")
    lines.append(f"  Liquidity        : {r['liquidity']}   avg sale price {money(r['avg_price'])}")
    lines += [f"  ! {w}" for w in r["warnings"]]
    lines.append(f"  Market link      : {MARKET_LINK.format(id=r['id'])}")
    return "\n".join(lines)


def print_suggestion(r, fee_pct):
    print("\n[BUY] " + format_suggestion(r, fee_pct))


def write_csv(path, results):
    fields = ["id", "name", "low", "qty", "cost_all", "second", "second_qty", "sell_at",
              "gap_pct", "net_per_unit", "profit_all", "roi_pct", "can_buy", "cost_yours",
              "profit_yours", "avg_price", "listings", "liquidity"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in results:
            if r["ok"]:
                w.writerow(r)
    print(f"\nSaved {path}")


# ------------------------------------------------------------------------ main

def pick_items(args, cfg, items):
    if args.command == "check":
        queries = args.items or cfg["watchlist"]
        if not queries:
            raise SystemExit('Give item names, e.g. check "Xanax", or fill "watchlist" in config.json.')
        return [find_item(items, q) for q in queries]

    skip = set(cfg["skip_types"])
    chosen = [it for it in items
              if it.get("is_tradable")
              and it.get("type") not in skip
              and (it.get("value") or {}).get("market_price", 0) >= cfg["min_market_price"]]
    chosen.sort(key=lambda it: it["value"]["market_price"], reverse=True)
    if args.max_items:
        chosen = chosen[:args.max_items]
    return chosen


def run_once(client, cfg, args, items, history):
    if args.money is not None:
        wallet = args.money
    else:
        try:
            wallet = spendable(client.money(), cfg.get("money_source", "wallet"))
        except TornAPIError as e:
            print(f"Could not read your wallet ({e}).\n"
                  "Use a Limited access key, or pass --money 5000000. Assuming unlimited money.",
                  file=sys.stderr)
            wallet = None

    targets = pick_items(args, cfg, items)
    if args.command == "scan":
        eta = len(targets) * cfg["request_delay"] / 60
        print(f"Scanning {len(targets)} items (about {eta:.0f} min)...", file=sys.stderr)

    results = []
    for i, item in enumerate(targets, 1):
        try:
            market = client.item_market(item["id"])
        except TornAPIError as e:
            print(f"  skip {item['name']}: {e}", file=sys.stderr)
            continue
        results.append(analyze(item, market, wallet, cfg["fee_percent"], history))
        if args.command == "scan" and i % 25 == 0:
            print(f"  {i}/{len(targets)}", file=sys.stderr)
    save_json(HISTORY_PATH, history)

    found = [r for r in results if is_opportunity(r, cfg["min_profit"], cfg["min_roi_percent"])]
    found.sort(key=lambda r: r["profit_yours"], reverse=True)

    print(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')}   wallet: "
          f"{money(wallet) if wallet is not None else 'unknown'}   fee: {cfg['fee_percent']:g}% ===\n")
    shown = results if (args.command == "check" or args.all) else found
    print_table(shown)
    for r in results:
        if not r["ok"] and args.command == "check":
            print(f"{r['name']}: {r['note']}")

    if found:
        print(f"\n{len(found)} flip(s) worth doing:")
        for r in found[:args.top]:
            print_suggestion(r, cfg["fee_percent"])
    else:
        print(f"\nNo flips above {money(cfg['min_profit'])} profit and "
              f"{cfg['min_roi_percent']:g}% ROI right now.")
    print("\n* = liquidity guessed from the order book. Run with --watch to measure real sales.")

    if args.csv:
        write_csv(args.csv, results)


def ask_api_key():
    """First run on the command line: ask for the key and save it to YOUR_TORN_API_KEY."""
    import getpass
    if not sys.stdin.isatty():
        raise SystemExit(f"No API key. Set the {API_KEY_ENV} environment variable or use --key.")
    print(f"No Torn API key found in the {API_KEY_ENV} environment variable.")
    print("Create one in Torn under Settings -> API Keys (Limited Access).")
    key = getpass.getpass("Paste your API key (hidden): ").strip()
    if not key:
        raise SystemExit("No API key given.")
    if set_api_key(key):
        print(f"Saved to the {API_KEY_ENV} user environment variable.")
    else:
        print(f"Using it for this run. To keep it, add  export {API_KEY_ENV}=...  "
              "to your shell profile.")
    return key


def main():
    p = argparse.ArgumentParser(description="Torn City item market flip finder (read-only).")
    p.add_argument("command", choices=["check", "scan"],
                   help="check: specific items / watchlist.  scan: every tradable item.")
    p.add_argument("items", nargs="*", help="item names or ids (check mode)")
    p.add_argument("--key", help=f"Torn API key for this run only (default: the {API_KEY_ENV} "
                                 "environment variable; you are asked for it if it is not set)")
    p.add_argument("--money", type=int, help="cash to spend instead of reading your wallet")
    p.add_argument("--fee", type=float, help="market fee percent (default 5)")
    p.add_argument("--min-profit", type=int, help="minimum total profit to suggest")
    p.add_argument("--min-roi", type=float, help="minimum ROI percent to suggest")
    p.add_argument("--max-items", type=int, help="scan mode: only the N most valuable items")
    p.add_argument("--top", type=int, default=10, help="how many suggestions to detail")
    p.add_argument("--all", action="store_true", help="scan mode: show every item, not only flips")
    p.add_argument("--watch", type=int, metavar="SECONDS", help="repeat every N seconds")
    p.add_argument("--csv", help="also save results to this CSV file")
    args = p.parse_args()

    cfg = load_config()
    if args.fee is not None:
        cfg["fee_percent"] = args.fee
    if args.min_profit is not None:
        cfg["min_profit"] = args.min_profit
    if args.min_roi is not None:
        cfg["min_roi_percent"] = args.min_roi

    key = args.key or cfg["api_key"]
    if not key:
        key = ask_api_key()

    client = TornClient(key, cfg["request_delay"])
    items = load_items(client)
    history = load_json(HISTORY_PATH, {})

    while True:
        try:
            run_once(client, cfg, args, items, history)
        except TornAPIError as e:
            print(f"Error: {e}", file=sys.stderr)
            if not args.watch:
                sys.exit(1)
        if not args.watch:
            break
        print(f"\nNext update in {args.watch} s (Ctrl+C to stop)...")
        try:
            time.sleep(args.watch)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except TornAPIError as e:
        sys.exit(f"Error: {e}")
