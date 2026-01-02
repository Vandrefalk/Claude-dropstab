#!/usr/bin/env python3
"""
Comprehensive Unlock Impact Data Collector

Collects ALL historical unlocks with price data around each unlock.
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
# CONFIGURATION - 50 COINS
# ============================================================================

TARGET_COINS = [
    # User's list of 50 coins (Dropstab slug -> display name)
    ("celestia", "TIA"),
    ("eigenlayer", "EIGEN"),
    ("layerzero", "ZRO"),
    ("optimism", "OP"),
    ("toncoin", "TON"),
    ("avalanche", "AVAX"),
    ("ethena", "ENA"),
    ("worldcoin", "WLD"),
    ("sui", "SUI"),
    ("plasma", "XPL"),
    ("berachain", "BERA"),
    ("walrus-protocol", "WAL"),
    ("monad", "MON"),
    ("zerogravity", "0G"),
    # ("canton-network", "CC"),  # no token
    ("movement", "MOVE"),
    ("sonic-svm", "S"),
    ("maplestory-universe", "NXPC"),
    ("io-net", "IO"),
    ("jito", "JTO"),
    ("morpho", "MORPHO"),
    ("centrifuge", "CFG"),
    ("huma-finance", "HUMA"),
    ("story-protocol", "IP"),
    ("ether-fi", "ETHFI"),
    ("altlayer", "ALT"),
    ("peaq", "PEAQ"),
    ("succinct", "PROVE"),
    ("axelar", "AXL"),
    ("chainopera-ai", "COAI"),
    ("humanity-protocol", "H"),
    ("lava-network", "LAVA"),
    ("redstone", "RED"),
    ("mask-network", "MASK"),
    ("illuvium", "ILV"),
    ("pudgy-penguins", "PENGU"),
    ("open-campus", "EDU"),
    ("mocaverse", "MOCA"),
    ("dimo", "DIMO"),
    ("geodnet", "GEOD"),
    ("bio-protocol", "BIO"),
    ("vana", "VANA"),
    ("mind-network", "FHE"),
    ("mountain-protocol", "USDM"),
    ("woo-network", "WOO"),
    ("lombard", "BARD"),
    ("babylon", "BABY"),
    ("world-liberty-financial", "WLFI"),
    ("sahara-ai", "SAHARA"),
    ("cysic", "CYS"),
]

# CoinGecko ID mapping
COINGECKO_IDS = {
    "celestia": "celestia",
    "eigenlayer": "eigenlayer",
    "layerzero": "layerzero",
    "optimism": "optimism",
    "toncoin": "the-open-network",
    "avalanche": "avalanche-2",
    "ethena": "ethena",
    "worldcoin": "worldcoin-wld",
    "sui": "sui",
    "plasma": "plasma-2",
    "berachain": "berachain",
    "walrus-protocol": "walrus-protocol",
    "monad": "monad",
    "zerogravity": "0g",
    "movement": "movement",
    "sonic-svm": "sonic-svm",
    "maplestory-universe": "maplestory-universe",
    "io-net": "io-net",
    "jito": "jito-governance-token",
    "morpho": "morpho",
    "centrifuge": "centrifuge",
    "huma-finance": "huma-finance",
    "story-protocol": "story-protocol",
    "ether-fi": "ether-fi",
    "altlayer": "altlayer",
    "peaq": "peaq",
    "succinct": "succinct",
    "axelar": "axelar",
    "chainopera-ai": "chainopera-ai",
    "humanity-protocol": "humanity-protocol",
    "lava-network": "lava-network",
    "redstone": "redstone-oracles",
    "mask-network": "mask-network",
    "illuvium": "illuvium",
    "pudgy-penguins": "pudgy-penguins",
    "open-campus": "open-campus",
    "mocaverse": "moca-network",
    "dimo": "dimo",
    "geodnet": "geodnet",
    "bio-protocol": "bio-protocol",
    "vana": "vana",
    "mind-network": "mind-network",
    "mountain-protocol": "mountain-protocol-usdm",
    "woo-network": "woo-network",
    "lombard": "lombard-staked-btc",
    "babylon": "babylon",
    "world-liberty-financial": "world-liberty-financial",
    "sahara-ai": "sahara-ai",
    "cysic": "cysic",
}

# Price points relative to unlock (days)
PRICE_OFFSETS = [-14, -10, -7, -5, -3, 0, 3, 5, 7, 10, 14]

# CoinGecko rate limiting
COINGECKO_DELAY = 1.2  # seconds between requests

# Output
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
        self._price_cache = {}

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
                logger.debug(f"CoinGecko error {resp.status_code}")
                return None
            return resp.json()
        except Exception as e:
            logger.debug(f"CoinGecko request failed: {e}")
            return None

    def get_coin_history(self, coin_id: str, date: str) -> Optional[dict]:
        """Get historical data. date format: DD-MM-YYYY"""
        cache_key = f"{coin_id}_{date}"
        if cache_key in self._price_cache:
            return self._price_cache[cache_key]

        data = self._get(f"coins/{coin_id}/history", {"date": date, "localization": "false"})
        if data:
            self._price_cache[cache_key] = data
        return data

    def get_price_on_date(self, coin_id: str, dt: datetime) -> Optional[float]:
        """Get price on specific date."""
        date_str = dt.strftime("%d-%m-%Y")
        data = self.get_coin_history(coin_id, date_str)
        if data and "market_data" in data:
            return data["market_data"].get("current_price", {}).get("usd")
        return None

    def get_market_data(self, coin_id: str, dt: datetime) -> dict:
        """Get comprehensive market data."""
        date_str = dt.strftime("%d-%m-%Y")
        data = self.get_coin_history(coin_id, date_str)
        if not data or "market_data" not in data:
            return {}
        md = data["market_data"]
        return {
            "price": md.get("current_price", {}).get("usd"),
            "market_cap": md.get("market_cap", {}).get("usd"),
            "volume_24h": md.get("total_volume", {}).get("usd"),
            "circulating_supply": md.get("circulating_supply"),
            "total_supply": md.get("total_supply"),
        }


# ============================================================================
# DATA COLLECTION
# ============================================================================

def collect_all_unlocks(dropstab: DropStabAPI, cg: CoinGeckoAPI,
                        coin_slug: str, coin_symbol: str,
                        output_file: Path, existing_dates: set) -> int:
    """Collect ALL unlocks for a coin and append to file."""

    logger.info(f"\n{'='*60}")
    logger.info(f"Processing: {coin_symbol} ({coin_slug})")
    logger.info(f"{'='*60}")

    cg_id = COINGECKO_IDS.get(coin_slug, coin_slug)
    today = datetime.now()
    collected = 0

    # Get past unlocks
    try:
        result = dropstab.get_token_unlocks_filtered(coin_slug, "PAST", "ASC")
        data = result.get("data", {})
        unlocks = data.get("tokenUnlocks", [])
        allocations = {a["id"]: a for a in data.get("allocations", [])}

        # Token info
        total_supply_from_api = data.get("totalSupply", 0)
        tge_date = data.get("tgeDate", "")

        if not unlocks:
            logger.warning(f"No unlocks found for {coin_slug}")
            return 0

        logger.info(f"Found {len(unlocks)} past unlocks")

    except Exception as e:
        logger.error(f"Error fetching unlocks for {coin_slug}: {e}")
        return 0

    # Process each unlock
    for idx, unlock in enumerate(unlocks):
        unlock_date_str = unlock.get("date", "")
        if not unlock_date_str:
            continue

        try:
            date_part = unlock_date_str.split("T")[0]
            unlock_date = datetime.strptime(date_part, "%Y-%m-%d")
        except:
            continue

        # Skip if already processed
        unlock_key = f"{coin_slug}_{date_part}_{unlock.get('allocationId', '')}"
        if unlock_key in existing_dates:
            continue

        # Skip if too recent (need +14 days data)
        if unlock_date > today - timedelta(days=14):
            continue

        # Get allocation info
        allocation_id = unlock.get("allocationId")
        allocation = allocations.get(allocation_id, {})
        allocation_name = unlock.get("allocationName", "") or allocation.get("name", "Unknown")

        # Basic unlock data
        tokens_amount = unlock.get("tokensAmount", 0) or 0
        pct_of_total = unlock.get("allTokensSharePercent", 0) or 0
        usd_value = unlock.get("usdAmount", 0) or 0
        is_tge = unlock.get("isTgeUnlock", False)
        market_cap_share = unlock.get("marketCapSharePercent", 0) or 0

        logger.info(f"  [{idx+1}/{len(unlocks)}] {date_part} - {allocation_name} ({pct_of_total:.2f}%)")

        row = {
            "coin": coin_symbol,
            "coin_slug": coin_slug,
            "unlock_date": date_part,
            "allocation": allocation_name,
            "allocation_id": allocation_id,
            "is_tge": is_tge,
            "tokens_amount": tokens_amount,
            "pct_of_total_supply": pct_of_total,
            "pct_of_market_cap": market_cap_share,
            "usd_value_at_unlock": usd_value,
            "tge_date": tge_date.split("T")[0] if tge_date else "",
        }

        # Get market data on unlock date from CoinGecko
        market_data = cg.get_market_data(cg_id, unlock_date)
        row["cg_price_on_unlock"] = market_data.get("price")
        row["cg_market_cap"] = market_data.get("market_cap")
        row["cg_volume_24h"] = market_data.get("volume_24h")
        row["cg_circulating_supply"] = market_data.get("circulating_supply")
        row["cg_total_supply"] = market_data.get("total_supply")

        # Calculate pct of circulating
        if tokens_amount and market_data.get("circulating_supply"):
            row["pct_of_circulating"] = (tokens_amount / market_data["circulating_supply"]) * 100
        else:
            row["pct_of_circulating"] = None

        # Get prices at all offsets
        for offset in PRICE_OFFSETS:
            target_date = unlock_date + timedelta(days=offset)
            if target_date > today:
                price = None
            else:
                price = cg.get_price_on_date(cg_id, target_date)

            if offset < 0:
                col_name = f"price_d{abs(offset)}_before"
            elif offset == 0:
                col_name = "price_on_unlock"
            else:
                col_name = f"price_d{offset}_after"
            row[col_name] = price

        # Get BTC/ETH prices for normalization
        row["btc_price"] = cg.get_price_on_date("bitcoin", unlock_date)
        row["eth_price"] = cg.get_price_on_date("ethereum", unlock_date)

        # Calculate price changes
        price_before_14 = row.get("price_d14_before")
        price_before_7 = row.get("price_d7_before")
        price_on = row.get("price_on_unlock")
        price_after_7 = row.get("price_d7_after")
        price_after_14 = row.get("price_d14_after")

        if price_before_7 and price_on and price_before_7 > 0:
            row["change_7d_before_pct"] = ((price_on - price_before_7) / price_before_7) * 100
        else:
            row["change_7d_before_pct"] = None

        if price_on and price_after_7 and price_on > 0:
            row["change_7d_after_pct"] = ((price_after_7 - price_on) / price_on) * 100
        else:
            row["change_7d_after_pct"] = None

        if price_before_14 and price_after_14 and price_before_14 > 0:
            row["change_14d_total_pct"] = ((price_after_14 - price_before_14) / price_before_14) * 100
        else:
            row["change_14d_total_pct"] = None

        # Volume ratio
        if usd_value and market_data.get("volume_24h") and market_data["volume_24h"] > 0:
            row["unlock_to_volume_ratio"] = usd_value / market_data["volume_24h"]
        else:
            row["unlock_to_volume_ratio"] = None

        # Append to CSV immediately
        append_row_to_csv(row, output_file)
        collected += 1
        existing_dates.add(unlock_key)

    logger.info(f"✓ Collected {collected} unlocks for {coin_symbol}")
    return collected


def get_csv_columns() -> list:
    """Define CSV column order."""
    price_cols = []
    for offset in PRICE_OFFSETS:
        if offset < 0:
            price_cols.append(f"price_d{abs(offset)}_before")
        elif offset == 0:
            price_cols.append("price_on_unlock")
        else:
            price_cols.append(f"price_d{offset}_after")

    return [
        # Identifiers
        "coin", "coin_slug", "unlock_date", "allocation", "allocation_id",
        "is_tge", "tge_date",
        # Unlock size
        "tokens_amount", "pct_of_total_supply", "pct_of_circulating",
        "pct_of_market_cap", "usd_value_at_unlock",
        # Market data from CoinGecko
        "cg_price_on_unlock", "cg_market_cap", "cg_volume_24h",
        "cg_circulating_supply", "cg_total_supply",
        # Price series
        *price_cols,
        # BTC/ETH for normalization
        "btc_price", "eth_price",
        # Calculated
        "change_7d_before_pct", "change_7d_after_pct", "change_14d_total_pct",
        "unlock_to_volume_ratio",
    ]


def append_row_to_csv(row: dict, output_file: Path):
    """Append single row to CSV file."""
    columns = get_csv_columns()
    file_exists = output_file.exists()

    with open(output_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def load_existing_entries(output_file: Path) -> set:
    """Load already processed entries to avoid duplicates."""
    existing = set()
    if output_file.exists():
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = f"{row.get('coin_slug', '')}_{row.get('unlock_date', '')}_{row.get('allocation_id', '')}"
                existing.add(key)
        logger.info(f"Loaded {len(existing)} existing entries")
    return existing


def main():
    """Main collection function."""
    import argparse

    parser = argparse.ArgumentParser(description="Collect comprehensive unlock impact data")
    parser.add_argument("--output", "-o", default="unlock_impact_data", help="Output directory")
    args = parser.parse_args()

    # Setup
    load_dotenv()
    api_key = os.getenv("DROPSTAB_API_KEY")

    if not api_key:
        logger.error("DROPSTAB_API_KEY not found in .env")
        return

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "unlock_impact_full.csv"

    dropstab = DropStabAPI(api_key)
    cg = CoinGeckoAPI()

    # Load existing to resume
    existing_dates = load_existing_entries(output_file)

    logger.info(f"Processing {len(TARGET_COINS)} coins")
    logger.info(f"Output: {output_file}")
    logger.info(f"Price offsets: {PRICE_OFFSETS}")

    total_collected = 0

    for i, (coin_slug, coin_symbol) in enumerate(TARGET_COINS):
        try:
            count = collect_all_unlocks(
                dropstab, cg, coin_slug, coin_symbol,
                output_file, existing_dates
            )
            total_collected += count
            logger.info(f"Progress: {i+1}/{len(TARGET_COINS)} coins, {total_collected} total unlocks")

        except Exception as e:
            logger.error(f"Error processing {coin_slug}: {e}")
            continue

    # Summary
    print("\n" + "="*70)
    print("COLLECTION COMPLETE")
    print("="*70)
    print(f"Total unlocks collected: {total_collected}")
    print(f"Output file: {output_file}")
    print("="*70)


if __name__ == "__main__":
    main()
