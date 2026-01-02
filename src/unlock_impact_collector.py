#!/usr/bin/env python3
"""
Comprehensive Unlock Impact Data Collector (Dropstab Only)

Collects ALL historical unlocks with price data around each unlock.
Uses ONLY Dropstab API (paid, no rate limits)

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

# Price points relative to unlock (days)
PRICE_OFFSETS = [-14, -10, -7, -5, -3, 0, 3, 5, 7, 10, 14]

# Output
OUTPUT_DIR = Path("unlock_impact_data")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_price_on_date(api: DropStabAPI, slug: str, dt: datetime) -> Optional[float]:
    """Get price on specific date from Dropstab."""
    try:
        date_str = dt.strftime("%Y-%m-%d")
        result = api.get_price_on_date(slug, date_str)
        data = result.get("data", {})
        if data:
            return data.get("USD")
        return None
    except Exception as e:
        logger.debug(f"Price not available for {slug} on {dt}: {e}")
        return None


def get_market_data(api: DropStabAPI, slug: str) -> dict:
    """Get current market data for a coin."""
    try:
        result = api.get_coin_detailed(slug)
        data = result.get("data", {})

        price_obj = data.get("price", {})
        price = price_obj.get("USD") if isinstance(price_obj, dict) else price_obj

        market_cap_obj = data.get("marketCap", {})
        market_cap = market_cap_obj.get("USD") if isinstance(market_cap_obj, dict) else market_cap_obj

        return {
            "price": price,
            "market_cap": market_cap,
            "circulating_supply": data.get("circulatingSupply"),
            "total_supply": data.get("totalSupply"),
            "fdv": data.get("fullyDilutedValuation"),
        }
    except Exception as e:
        logger.debug(f"Market data error for {slug}: {e}")
        return {}


# ============================================================================
# DATA COLLECTION
# ============================================================================

def collect_all_unlocks(api: DropStabAPI, coin_slug: str, coin_symbol: str,
                        output_file: Path, existing_dates: set) -> int:
    """Collect ALL unlocks for a coin and append to file."""

    logger.info(f"\n{'='*60}")
    logger.info(f"Processing: {coin_symbol} ({coin_slug})")
    logger.info(f"{'='*60}")

    today = datetime.now()
    collected = 0

    # Get past unlocks from Dropstab
    try:
        result = api.get_token_unlocks_filtered(coin_slug, "PAST", "ASC")
        data = result.get("data", {})
        unlocks = data.get("tokenUnlocks", [])
        allocations = {a["id"]: a for a in data.get("allocations", [])}

        # Token info
        tge_date = data.get("tgeDate", "")
        total_locked_pct = data.get("totalTokensLockedPercent", 0)
        total_unlocked_pct = data.get("totalTokensUnlockedPercent", 0)

        if not unlocks:
            logger.warning(f"No unlocks found for {coin_slug}")
            return 0

        logger.info(f"Found {len(unlocks)} past unlocks")

    except Exception as e:
        logger.error(f"Error fetching unlocks for {coin_slug}: {e}")
        return 0

    # Get current market data
    market_info = get_market_data(api, coin_slug)

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
        fdv_share = unlock.get("fdvSharePercent", 0) or 0

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
            "pct_of_fdv": fdv_share,
            "usd_value_at_unlock": usd_value,
            "tge_date": tge_date.split("T")[0] if tge_date else "",
            # Current market info (for reference)
            "current_price": market_info.get("price"),
            "current_market_cap": market_info.get("market_cap"),
            "current_circulating": market_info.get("circulating_supply"),
            "current_total_supply": market_info.get("total_supply"),
            "current_fdv": market_info.get("fdv"),
        }

        # Get prices at all offsets from Dropstab
        for offset in PRICE_OFFSETS:
            target_date = unlock_date + timedelta(days=offset)
            if target_date > today:
                price = None
            else:
                price = get_price_on_date(api, coin_slug, target_date)

            if offset < 0:
                col_name = f"price_d{abs(offset)}_before"
            elif offset == 0:
                col_name = "price_on_unlock"
            else:
                col_name = f"price_d{offset}_after"
            row[col_name] = price

        # Get BTC price for normalization
        row["btc_price_on_unlock"] = get_price_on_date(api, "bitcoin", unlock_date)

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
        "tokens_amount", "pct_of_total_supply", "pct_of_market_cap", "pct_of_fdv",
        "usd_value_at_unlock",
        # Current market data
        "current_price", "current_market_cap", "current_circulating",
        "current_total_supply", "current_fdv",
        # Price series
        *price_cols,
        # BTC for normalization
        "btc_price_on_unlock",
        # Calculated
        "change_7d_before_pct", "change_7d_after_pct", "change_14d_total_pct",
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

    api = DropStabAPI(api_key)

    # Load existing to resume
    existing_dates = load_existing_entries(output_file)

    logger.info(f"Processing {len(TARGET_COINS)} coins")
    logger.info(f"Output: {output_file}")
    logger.info(f"Price offsets: {PRICE_OFFSETS}")
    logger.info("Using Dropstab API only (no CoinGecko)")

    total_collected = 0

    for i, (coin_slug, coin_symbol) in enumerate(TARGET_COINS):
        try:
            count = collect_all_unlocks(
                api, coin_slug, coin_symbol,
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
