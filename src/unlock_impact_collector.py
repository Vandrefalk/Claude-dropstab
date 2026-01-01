#!/usr/bin/env python3
"""
Unlock Impact Data Collector

Collects comprehensive data for analyzing token unlock impact on prices.
Sources: Dropstab API (unlocks) + CoinGecko API (prices, market data)

Run in background:
    nohup python3 src/unlock_impact_collector.py > unlock_collector.log 2>&1 &
"""

import os
import sys
import json
import csv
import time
import logging
import signal
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from api_client import DropStabAPI

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('unlock_collector_debug.log')
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Top coins with significant unlocks
TARGET_COINS = [
    # Layer 2s
    "arbitrum", "optimism", "starknet", "zksync-era", "manta-network",
    # New L1s
    "aptos", "sui", "celestia", "sei", "injective",
    # DeFi/Infra
    "pyth-network", "jupiter", "eigenlayer", "wormhole", "blur",
    # Others with major unlocks
    "worldcoin", "arkham", "cyberconnect", "altlayer", "dymension",
    "zetachain", "portal-2", "pixels", "sleepless-ai", "xai-blockchain",
    "nft-worlds", "ronin", "immutable-x", "axie-infinity", "gala",
]

# CoinGecko ID mapping (Dropstab slug -> CoinGecko ID)
COINGECKO_IDS = {
    "arbitrum": "arbitrum",
    "optimism": "optimism",
    "starknet": "starknet",
    "zksync-era": "zksync",
    "manta-network": "manta-network",
    "aptos": "aptos",
    "sui": "sui",
    "celestia": "celestia",
    "sei": "sei-network",
    "injective": "injective-protocol",
    "pyth-network": "pyth-network",
    "jupiter": "jupiter-exchange-solana",
    "eigenlayer": "eigenlayer",
    "wormhole": "wormhole",
    "blur": "blur",
    "worldcoin": "worldcoin-wld",
    "arkham": "arkham",
    "cyberconnect": "cyberconnect",
    "altlayer": "altlayer",
    "dymension": "dymension",
    "zetachain": "zetachain",
    "portal-2": "portal",
    "pixels": "pixels",
    "sleepless-ai": "sleepless-ai",
    "xai-blockchain": "xai-blockchain",
    "ronin": "ronin",
    "immutable-x": "immutable-x",
    "axie-infinity": "axie-infinity",
    "gala": "gala",
}

# Allocations to include (skip airdrops)
VALID_ALLOCATIONS = [
    "team", "investor", "investors", "private", "seed",
    "advisors", "advisor", "foundation", "ecosystem",
    "treasury", "core contributors", "early backers",
    "strategic", "partners", "reserve"
]

# Minimum unlock size (% of circulating supply)
MIN_UNLOCK_PCT = 1.0

# CoinGecko rate limiting
COINGECKO_DELAY = 1.5  # seconds between requests (free tier ~30/min)

# Output directory
OUTPUT_DIR = Path("unlock_impact_data")


# ============================================================================
# COINGECKO API CLIENT
# ============================================================================

class CoinGeckoAPI:
    """Simple CoinGecko API client."""

    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self, delay: float = COINGECKO_DELAY):
        self.delay = delay
        self.session = requests.Session()
        self._last_request = 0

    def _rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.time()

    def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        self._rate_limit()
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                logger.warning("CoinGecko rate limited, waiting 60s...")
                time.sleep(60)
                return self._get(endpoint, params)
            if resp.status_code != 200:
                logger.debug(f"CoinGecko error {resp.status_code}: {resp.text[:200]}")
                return None
            return resp.json()
        except Exception as e:
            logger.debug(f"CoinGecko request failed: {e}")
            return None

    def get_coin_history(self, coin_id: str, date: str) -> Optional[dict]:
        """
        Get historical data for a coin on specific date.
        date format: DD-MM-YYYY
        """
        return self._get(f"coins/{coin_id}/history", {"date": date, "localization": "false"})

    def get_coin_market_chart_range(self, coin_id: str, from_ts: int, to_ts: int) -> Optional[dict]:
        """Get price/volume data for date range."""
        return self._get(f"coins/{coin_id}/market_chart/range", {
            "vs_currency": "usd",
            "from": from_ts,
            "to": to_ts
        })

    def get_simple_price(self, coin_ids: List[str]) -> Optional[dict]:
        """Get current prices for multiple coins."""
        return self._get("simple/price", {
            "ids": ",".join(coin_ids),
            "vs_currencies": "usd",
            "include_market_cap": "true",
            "include_24hr_vol": "true"
        })


# ============================================================================
# DATA COLLECTION FUNCTIONS
# ============================================================================

def date_to_coingecko(dt: datetime) -> str:
    """Convert datetime to CoinGecko format DD-MM-YYYY."""
    return dt.strftime("%d-%m-%Y")

def date_to_str(dt: datetime) -> str:
    """Convert datetime to YYYY-MM-DD."""
    return dt.strftime("%Y-%m-%d")

def parse_date(s: str) -> Optional[datetime]:
    """Parse ISO date string."""
    if not s:
        return None
    try:
        if "T" in s:
            s = s.split("T")[0]
        return datetime.strptime(s, "%Y-%m-%d")
    except:
        return None

def is_valid_allocation(name: str) -> bool:
    """Check if allocation should be included."""
    if not name:
        return False
    name_lower = name.lower()
    # Skip airdrops
    if "airdrop" in name_lower or "drop" in name_lower:
        return False
    # Check for valid allocations
    for valid in VALID_ALLOCATIONS:
        if valid in name_lower:
            return True
    return False

def get_price_on_date(cg: CoinGeckoAPI, coin_id: str, dt: datetime) -> Optional[float]:
    """Get price on specific date from CoinGecko."""
    data = cg.get_coin_history(coin_id, date_to_coingecko(dt))
    if data and "market_data" in data:
        return data["market_data"].get("current_price", {}).get("usd")
    return None

def get_market_data_on_date(cg: CoinGeckoAPI, coin_id: str, dt: datetime) -> dict:
    """Get comprehensive market data on specific date."""
    data = cg.get_coin_history(coin_id, date_to_coingecko(dt))
    if not data or "market_data" not in data:
        return {}

    md = data["market_data"]
    return {
        "price": md.get("current_price", {}).get("usd"),
        "market_cap": md.get("market_cap", {}).get("usd"),
        "total_volume": md.get("total_volume", {}).get("usd"),
        "circulating_supply": md.get("circulating_supply"),
        "total_supply": md.get("total_supply"),
    }

def get_volume_avg_7d(cg: CoinGeckoAPI, coin_id: str, unlock_date: datetime) -> Optional[float]:
    """Get average volume for 7 days before unlock."""
    from_ts = int((unlock_date - timedelta(days=7)).timestamp())
    to_ts = int((unlock_date - timedelta(days=1)).timestamp())

    data = cg.get_coin_market_chart_range(coin_id, from_ts, to_ts)
    if data and "total_volumes" in data:
        volumes = [v[1] for v in data["total_volumes"] if v[1] > 0]
        if volumes:
            return sum(volumes) / len(volumes)
    return None

def collect_price_series(cg: CoinGeckoAPI, coin_id: str, unlock_date: datetime) -> dict:
    """Collect prices at various points around unlock."""
    prices = {}

    # Days relative to unlock
    offsets = {
        "price_d7_before": -7,
        "price_d3_before": -3,
        "price_d1_before": -1,
        "price_on_unlock": 0,
        "price_d1_after": 1,
        "price_d3_after": 3,
        "price_d7_after": 7,
        "price_d14_after": 14,
    }

    for field, days in offsets.items():
        target_date = unlock_date + timedelta(days=days)
        # Don't fetch future dates
        if target_date > datetime.now():
            prices[field] = None
        else:
            prices[field] = get_price_on_date(cg, coin_id, target_date)

    return prices

def get_btc_eth_prices(cg: CoinGeckoAPI, dt: datetime) -> dict:
    """Get BTC and ETH prices on specific date."""
    btc = get_price_on_date(cg, "bitcoin", dt)
    eth = get_price_on_date(cg, "ethereum", dt)
    return {"btc_price": btc, "eth_price": eth}


def calculate_derived_fields(row: dict) -> dict:
    """Calculate derived metrics."""
    derived = {}

    # Unlock to volume ratio
    if row.get("usd_value_unlocked") and row.get("volume_24h") and row["volume_24h"] > 0:
        derived["unlock_to_daily_volume_ratio"] = row["usd_value_unlocked"] / row["volume_24h"]
    else:
        derived["unlock_to_daily_volume_ratio"] = None

    # 7d price change before unlock
    if row.get("price_d7_before") and row.get("price_on_unlock") and row["price_d7_before"] > 0:
        derived["change_7d_before"] = ((row["price_on_unlock"] - row["price_d7_before"]) / row["price_d7_before"]) * 100
    else:
        derived["change_7d_before"] = None

    # 7d price change after unlock
    if row.get("price_on_unlock") and row.get("price_d7_after") and row["price_on_unlock"] > 0:
        derived["change_7d_after"] = ((row["price_d7_after"] - row["price_on_unlock"]) / row["price_on_unlock"]) * 100
    else:
        derived["change_7d_after"] = None

    # 7d change vs BTC
    if row.get("price_on_unlock") and row.get("price_d7_after") and row.get("btc_price_on_unlock"):
        btc_after = get_price_on_date(CoinGeckoAPI(), "bitcoin",
                                       parse_date(row["unlock_date"]) + timedelta(days=7)) if row.get("unlock_date") else None
        if btc_after and row["btc_price_on_unlock"] > 0:
            coin_change = (row["price_d7_after"] - row["price_on_unlock"]) / row["price_on_unlock"]
            btc_change = (btc_after - row["btc_price_on_unlock"]) / row["btc_price_on_unlock"]
            derived["change_7d_vs_btc"] = (coin_change - btc_change) * 100
        else:
            derived["change_7d_vs_btc"] = None
    else:
        derived["change_7d_vs_btc"] = None

    return derived


# ============================================================================
# MAIN COLLECTION LOGIC
# ============================================================================

def collect_coin_unlocks(dropstab: DropStabAPI, cg: CoinGeckoAPI,
                         coin_slug: str, cg_id: str) -> List[dict]:
    """Collect all qualifying unlocks for a coin."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing: {coin_slug} (CoinGecko: {cg_id})")
    logger.info(f"{'='*60}")

    results = []
    today = datetime.now()
    one_year_ago = today - timedelta(days=365)

    # Get past unlocks from Dropstab
    try:
        unlock_data = dropstab.get_token_unlocks_filtered(coin_slug, "PAST", "ASC")
        data = unlock_data.get("data", {})
        unlocks = data.get("tokenUnlocks", [])

        if not unlocks:
            logger.warning(f"No unlocks found for {coin_slug}")
            return []

        logger.info(f"Found {len(unlocks)} past unlocks")

        # Get allocations for context
        allocations = {a["id"]: a for a in data.get("allocations", [])}

    except Exception as e:
        logger.error(f"Error fetching unlocks for {coin_slug}: {e}")
        return []

    # Filter and process unlocks
    processed = 0
    skipped_date = 0
    skipped_size = 0
    skipped_allocation = 0

    for unlock in unlocks:
        unlock_date = parse_date(unlock.get("date", ""))
        if not unlock_date:
            continue

        # Filter: last 12 months only
        if unlock_date < one_year_ago:
            skipped_date += 1
            continue

        # Filter: skip future/very recent (need 14d after data)
        if unlock_date > today - timedelta(days=14):
            skipped_date += 1
            continue

        # Get allocation info
        allocation_id = unlock.get("allocationId")
        allocation = allocations.get(allocation_id, {})
        allocation_name = unlock.get("allocationName", "") or allocation.get("name", "")

        # Filter: valid allocation types only
        if not is_valid_allocation(allocation_name):
            skipped_allocation += 1
            continue

        # Get unlock size
        tokens_pct = unlock.get("allTokensSharePercent", 0) or 0

        # Filter: minimum size
        if tokens_pct < MIN_UNLOCK_PCT:
            skipped_size += 1
            continue

        # This unlock qualifies! Collect data
        logger.info(f"  Processing unlock: {date_to_str(unlock_date)} - {allocation_name} ({tokens_pct:.2f}%)")

        # Basic unlock data
        row = {
            "coin": coin_slug.upper().replace("-", ""),
            "coin_slug": coin_slug,
            "coingecko_id": cg_id,
            "unlock_date": date_to_str(unlock_date),
            "unlock_type": "cliff",  # We're filtering for cliff unlocks
            "allocation": allocation_name,
            "tokens_amount": unlock.get("tokensAmount", 0) or 0,
            "pct_of_total": tokens_pct,
            "is_tge": unlock.get("isTgeUnlock", False),
        }

        # Get market data on unlock date from CoinGecko
        market_data = get_market_data_on_date(cg, cg_id, unlock_date)
        row.update({
            "market_cap": market_data.get("market_cap"),
            "circulating_supply": market_data.get("circulating_supply"),
            "total_supply": market_data.get("total_supply"),
            "volume_24h": market_data.get("total_volume"),
        })

        # Calculate pct of circulating
        if row["tokens_amount"] and row.get("circulating_supply") and row["circulating_supply"] > 0:
            row["pct_of_circulating"] = (row["tokens_amount"] / row["circulating_supply"]) * 100
        else:
            row["pct_of_circulating"] = None

        # Calculate FDV
        if row.get("total_supply") and market_data.get("price"):
            row["fdv"] = row["total_supply"] * market_data["price"]
        else:
            row["fdv"] = None

        # USD value of unlock
        if row["tokens_amount"] and market_data.get("price"):
            row["usd_value_unlocked"] = row["tokens_amount"] * market_data["price"]
        else:
            row["usd_value_unlocked"] = unlock.get("usdAmount", 0) or 0

        # Get 7d average volume before unlock
        row["volume_avg_7d"] = get_volume_avg_7d(cg, cg_id, unlock_date)

        # Get price series around unlock
        prices = collect_price_series(cg, cg_id, unlock_date)
        row.update(prices)

        # Get BTC/ETH for normalization
        btc_eth = get_btc_eth_prices(cg, unlock_date)
        row["btc_price_on_unlock"] = btc_eth["btc_price"]
        row["eth_price_on_unlock"] = btc_eth["eth_price"]

        # Calculate derived fields
        derived = calculate_derived_fields(row)
        row.update(derived)

        results.append(row)
        processed += 1

        # Progress
        if processed % 5 == 0:
            logger.info(f"  Processed {processed} qualifying unlocks...")

    logger.info(f"Summary for {coin_slug}:")
    logger.info(f"  - Processed: {processed}")
    logger.info(f"  - Skipped (date): {skipped_date}")
    logger.info(f"  - Skipped (size): {skipped_size}")
    logger.info(f"  - Skipped (allocation): {skipped_allocation}")

    return results


def save_results(results: List[dict], output_dir: Path):
    """Save results to CSV and JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if not results:
        logger.warning("No results to save")
        return

    # Define column order
    columns = [
        # Unlock info
        "coin", "coin_slug", "coingecko_id", "unlock_date", "unlock_type",
        "allocation", "is_tge", "tokens_amount", "pct_of_circulating", "pct_of_total",
        "usd_value_unlocked",
        # Market data
        "market_cap", "circulating_supply", "total_supply", "fdv",
        "volume_24h", "volume_avg_7d",
        # Price series
        "price_d7_before", "price_d3_before", "price_d1_before",
        "price_on_unlock", "price_d1_after", "price_d3_after",
        "price_d7_after", "price_d14_after",
        # Normalization
        "btc_price_on_unlock", "eth_price_on_unlock",
        # Derived
        "unlock_to_daily_volume_ratio", "change_7d_before",
        "change_7d_after", "change_7d_vs_btc",
    ]

    # CSV
    csv_file = output_dir / "unlock_impact_dataset.csv"
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)
    logger.info(f"Saved CSV: {csv_file} ({len(results)} rows)")

    # JSON (for backup)
    json_file = output_dir / "unlock_impact_dataset.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"Saved JSON: {json_file}")


def print_summary(results: List[dict]):
    """Print collection summary."""
    print("\n" + "="*70)
    print("UNLOCK IMPACT DATA COLLECTION SUMMARY")
    print("="*70)

    if not results:
        print("No data collected")
        return

    # Stats by coin
    by_coin = {}
    for r in results:
        coin = r["coin"]
        if coin not in by_coin:
            by_coin[coin] = []
        by_coin[coin].append(r)

    print(f"\nTotal unlocks collected: {len(results)}")
    print(f"Coins covered: {len(by_coin)}")

    print("\nBreakdown by coin:")
    for coin, unlocks in sorted(by_coin.items()):
        avg_pct = sum(u.get("pct_of_total", 0) or 0 for u in unlocks) / len(unlocks)
        print(f"  {coin}: {len(unlocks)} unlocks (avg {avg_pct:.2f}% of total supply)")

    # Stats on price impact
    changes_after = [r["change_7d_after"] for r in results if r.get("change_7d_after") is not None]
    if changes_after:
        avg_change = sum(changes_after) / len(changes_after)
        negative = len([c for c in changes_after if c < 0])
        positive = len([c for c in changes_after if c > 0])

        print(f"\nPrice Impact (7d after unlock):")
        print(f"  Average change: {avg_change:+.2f}%")
        print(f"  Negative: {negative} ({100*negative/len(changes_after):.1f}%)")
        print(f"  Positive: {positive} ({100*positive/len(changes_after):.1f}%)")

    print("="*70)


def main():
    """Main collection function."""
    import argparse

    parser = argparse.ArgumentParser(description="Collect unlock impact data")
    parser.add_argument("--coins", nargs="+", default=None, help="Specific coins to process")
    parser.add_argument("--output", "-o", default="unlock_impact_data", help="Output directory")
    parser.add_argument("--resume", action="store_true", help="Resume from existing data")
    args = parser.parse_args()

    # Setup
    load_dotenv()
    api_key = os.getenv("DROPSTAB_API_KEY")

    if not api_key:
        logger.error("DROPSTAB_API_KEY not found in .env")
        return

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    dropstab = DropStabAPI(api_key)
    cg = CoinGeckoAPI()

    # Determine which coins to process
    if args.coins:
        coins_to_process = args.coins
    else:
        coins_to_process = TARGET_COINS

    # Load existing results if resuming
    all_results = []
    processed_coins = set()

    if args.resume:
        json_file = output_dir / "unlock_impact_dataset.json"
        if json_file.exists():
            with open(json_file) as f:
                all_results = json.load(f)
            processed_coins = set(r["coin_slug"] for r in all_results)
            logger.info(f"Resuming: loaded {len(all_results)} existing results from {len(processed_coins)} coins")

    logger.info(f"Processing {len(coins_to_process)} coins")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Filters: unlocks > {MIN_UNLOCK_PCT}% of supply, last 12 months")

    # Process each coin
    for i, coin_slug in enumerate(coins_to_process):
        if coin_slug in processed_coins:
            logger.info(f"Skipping {coin_slug} (already processed)")
            continue

        cg_id = COINGECKO_IDS.get(coin_slug, coin_slug)

        try:
            coin_results = collect_coin_unlocks(dropstab, cg, coin_slug, cg_id)
            all_results.extend(coin_results)

            # Save incrementally after each coin
            save_results(all_results, output_dir)
            logger.info(f"✓ Progress: {i+1}/{len(coins_to_process)} coins, {len(all_results)} total unlocks")

        except Exception as e:
            logger.error(f"Error processing {coin_slug}: {e}")
            # Save what we have so far
            save_results(all_results, output_dir)
            continue

    # Final summary
    print_summary(all_results)
    logger.info(f"\nDone! Results saved to {output_dir}/")


if __name__ == "__main__":
    main()
