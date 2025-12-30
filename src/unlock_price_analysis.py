#!/usr/bin/env python3
"""
Unlock Price Impact Analysis

Hypothesis: There's a correlation between token unlocks and price movements.

For each coin:
1. Get past unlock events
2. For each unlock, get price 5 days before and 5 days after
3. Get unlock size (tokens amount, % of supply)
4. Get market cap at unlock time

Output: CSV with all data for analysis
"""

import os
import sys
import json
import csv
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from api_client import DropStabAPI

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# Test coins for hypothesis validation
TEST_COINS = [
    "arbitrum",      # ARB - large unlocks
    "optimism",      # OP - layer 2 with vesting
    "aptos",         # APT - new L1 with unlocks
    "sui",           # SUI - recent launches
    "celestia",      # TIA - modular blockchain
]


def date_to_str(dt: datetime) -> str:
    """Convert datetime to YYYY-MM-DD string."""
    return dt.strftime("%Y-%m-%d")


def str_to_date(s: str) -> datetime:
    """Parse date string to datetime."""
    # Handle ISO format with timezone
    if "T" in s:
        s = s.split("T")[0]
    return datetime.strptime(s, "%Y-%m-%d")


def get_price_safe(api: DropStabAPI, slug: str, date_str: str) -> Optional[float]:
    """Get price on date, return None if not available."""
    try:
        result = api.get_price_on_date(slug, date_str)
        data = result.get("data", {})
        if data:
            return data.get("USD", 0) or 0
        return None
    except Exception as e:
        logger.debug(f"Price not available for {slug} on {date_str}: {e}")
        return None


def get_market_cap_on_date(api: DropStabAPI, slug: str, date: datetime) -> Optional[float]:
    """Get market cap on specific date using chart interval."""
    try:
        from_date = (date - timedelta(days=1)).isoformat() + "Z"
        to_date = (date + timedelta(days=1)).isoformat() + "Z"

        result = api.get_chart_by_interval(slug, from_date, to_date)
        data = result.get("data", [])

        if data:
            # Find closest data point
            target_ts = date.timestamp() * 1000
            closest = min(data, key=lambda x: abs(x.get("timestamp", 0) - target_ts))
            return closest.get("marketCap", 0) or 0
        return None
    except Exception as e:
        logger.debug(f"Market cap not available for {slug} on {date}: {e}")
        return None


def analyze_coin_unlocks(api: DropStabAPI, slug: str) -> list[dict]:
    """Analyze all past unlocks for a coin."""
    logger.info(f"\n{'='*50}")
    logger.info(f"Analyzing: {slug}")
    logger.info(f"{'='*50}")

    # Get past unlocks
    try:
        result = api.get_token_unlocks_filtered(slug, timeline_filter="PAST", sort_order="ASC")
        data = result.get("data", {})
        unlocks = data.get("tokenUnlocks", [])

        if not unlocks:
            logger.warning(f"No past unlocks found for {slug}")
            return []

        logger.info(f"Found {len(unlocks)} past unlocks")

    except Exception as e:
        logger.error(f"Error fetching unlocks for {slug}: {e}")
        return []

    # Get current coin info
    try:
        coin_info = api.get_coin_detailed(slug)
        coin_data = coin_info.get("data", {})
        current_price = coin_data.get("price", {}).get("USD", 0) or 0
        total_supply = coin_data.get("totalSupply", 0) or 0
    except:
        current_price = 0
        total_supply = 0

    results = []
    today = datetime.now()

    for i, unlock in enumerate(unlocks):
        unlock_date_str = unlock.get("date", "")
        if not unlock_date_str:
            continue

        try:
            unlock_date = str_to_date(unlock_date_str)
        except:
            continue

        # Skip if unlock is too recent (less than 5 days ago)
        if (today - unlock_date).days < 5:
            logger.debug(f"Skipping recent unlock: {unlock_date_str}")
            continue

        # Skip if unlock is before coin trading started (no price data)
        # Usually coins start trading at TGE

        tokens_amount = unlock.get("tokensAmount", 0) or 0
        tokens_percent = unlock.get("allTokensSharePercent", 0) or 0
        usd_amount = unlock.get("usdAmount", 0) or 0
        allocation_name = unlock.get("allocationName", "")
        is_tge = unlock.get("isTgeUnlock", False)

        # Get prices: -5, -3, -1, 0, +1, +3, +5 days
        price_minus_5 = get_price_safe(api, slug, date_to_str(unlock_date - timedelta(days=5)))
        price_minus_3 = get_price_safe(api, slug, date_to_str(unlock_date - timedelta(days=3)))
        price_minus_1 = get_price_safe(api, slug, date_to_str(unlock_date - timedelta(days=1)))
        price_on_date = get_price_safe(api, slug, date_to_str(unlock_date))
        price_plus_1 = get_price_safe(api, slug, date_to_str(unlock_date + timedelta(days=1)))
        price_plus_3 = get_price_safe(api, slug, date_to_str(unlock_date + timedelta(days=3)))
        price_plus_5 = get_price_safe(api, slug, date_to_str(unlock_date + timedelta(days=5)))

        # Calculate price changes
        def calc_change(before: Optional[float], after: Optional[float]) -> Optional[float]:
            if before and after and before > 0:
                return ((after - before) / before) * 100
            return None

        change_5d_before_to_unlock = calc_change(price_minus_5, price_on_date)
        change_unlock_to_5d_after = calc_change(price_on_date, price_plus_5)
        change_minus5_to_plus5 = calc_change(price_minus_5, price_plus_5)

        # Get market cap on unlock date
        market_cap = get_market_cap_on_date(api, slug, unlock_date)

        result = {
            "coin": slug,
            "unlock_date": date_to_str(unlock_date),
            "allocation": allocation_name,
            "is_tge": is_tge,

            # Unlock size
            "tokens_amount": tokens_amount,
            "tokens_percent": tokens_percent,
            "usd_amount": usd_amount,

            # Prices around unlock
            "price_minus_5d": price_minus_5,
            "price_minus_3d": price_minus_3,
            "price_minus_1d": price_minus_1,
            "price_on_unlock": price_on_date,
            "price_plus_1d": price_plus_1,
            "price_plus_3d": price_plus_3,
            "price_plus_5d": price_plus_5,

            # Price changes (%)
            "change_5d_before": change_5d_before_to_unlock,
            "change_5d_after": change_unlock_to_5d_after,
            "change_total_10d": change_minus5_to_plus5,

            # Market context
            "market_cap": market_cap,
            "current_price": current_price,
        }

        results.append(result)

        if (i + 1) % 5 == 0:
            logger.info(f"Processed {i + 1}/{len(unlocks)} unlocks")

    logger.info(f"Collected data for {len(results)} unlocks")
    return results


def save_results(all_results: list[dict], output_dir: Path):
    """Save results to CSV and JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    json_file = output_dir / "unlock_price_analysis.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved JSON: {json_file}")

    # CSV
    if all_results:
        csv_file = output_dir / "unlock_price_analysis.csv"
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=all_results[0].keys())
            writer.writeheader()
            writer.writerows(all_results)
        logger.info(f"Saved CSV: {csv_file}")


def print_summary(all_results: list[dict]):
    """Print analysis summary."""
    print("\n" + "="*70)
    print("UNLOCK PRICE ANALYSIS SUMMARY")
    print("="*70)

    if not all_results:
        print("No data collected")
        return

    # Group by coin
    by_coin = {}
    for r in all_results:
        coin = r["coin"]
        if coin not in by_coin:
            by_coin[coin] = []
        by_coin[coin].append(r)

    for coin, unlocks in by_coin.items():
        print(f"\n📊 {coin.upper()}:")
        print("-"*50)
        print(f"  Total unlocks analyzed: {len(unlocks)}")

        # Average price changes
        changes_before = [u["change_5d_before"] for u in unlocks if u["change_5d_before"] is not None]
        changes_after = [u["change_5d_after"] for u in unlocks if u["change_5d_after"] is not None]

        if changes_before:
            avg_before = sum(changes_before) / len(changes_before)
            print(f"  Avg price change 5d BEFORE unlock: {avg_before:+.2f}%")

        if changes_after:
            avg_after = sum(changes_after) / len(changes_after)
            print(f"  Avg price change 5d AFTER unlock: {avg_after:+.2f}%")

        # Largest unlock
        largest = max(unlocks, key=lambda x: x.get("tokens_percent", 0) or 0)
        print(f"  Largest unlock: {largest['tokens_percent']:.2f}% on {largest['unlock_date']}")
        if largest["change_5d_after"] is not None:
            print(f"    → Price change after: {largest['change_5d_after']:+.2f}%")

    # Overall stats
    print("\n" + "="*70)
    print("OVERALL STATISTICS:")
    print("-"*50)

    all_before = [u["change_5d_before"] for u in all_results if u["change_5d_before"] is not None]
    all_after = [u["change_5d_after"] for u in all_results if u["change_5d_after"] is not None]

    if all_before:
        print(f"Average price change 5d BEFORE unlock: {sum(all_before)/len(all_before):+.2f}%")
    if all_after:
        print(f"Average price change 5d AFTER unlock: {sum(all_after)/len(all_after):+.2f}%")

    # Correlation hint
    negative_after = len([x for x in all_after if x < 0])
    positive_after = len([x for x in all_after if x > 0])

    print(f"\nUnlocks with NEGATIVE price after: {negative_after} ({100*negative_after/len(all_after):.1f}%)")
    print(f"Unlocks with POSITIVE price after: {positive_after} ({100*positive_after/len(all_after):.1f}%)")

    print("="*70)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Analyze unlock price impact")
    parser.add_argument("--coins", nargs="+", default=TEST_COINS, help="Coins to analyze")
    parser.add_argument("--output", "-o", default="unlock_analysis", help="Output directory")

    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("DROPSTAB_API_KEY")

    if not api_key:
        print("ERROR: DROPSTAB_API_KEY not found in .env")
        return

    api = DropStabAPI(api_key)
    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Analyzing {len(args.coins)} coins: {', '.join(args.coins)}")
    print(f"Output: {output_path}/")

    all_results = []

    for i, coin in enumerate(args.coins):
        results = analyze_coin_unlocks(api, coin)
        all_results.extend(results)

        # Save after each coin (incremental save)
        save_results(all_results, output_path)
        print(f"✓ Saved progress: {i+1}/{len(args.coins)} coins, {len(all_results)} unlocks total")

    print_summary(all_results)


if __name__ == "__main__":
    main()
