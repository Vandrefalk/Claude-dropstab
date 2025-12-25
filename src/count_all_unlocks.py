#!/usr/bin/env python3
"""
Count EXACT number of unlock events on DropStab.

Queries all supported coins and counts every unlock event.
"""

import os
import sys
import json
import time
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from api_client import DropStabAPI

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def count_all_unlocks(api_key: str, output_file: str = None):
    """
    Count exact number of unlock events on DropStab.

    Args:
        api_key: DropStab API key
        output_file: Optional file to save detailed results

    Returns:
        dict with total counts
    """
    api = DropStabAPI(api_key)

    # Get all supported coins for token unlocks
    logger.info("Fetching supported coins for token unlocks...")

    try:
        supported_response = api._request("/tokenUnlocks/supportedCoins")
        supported_coins = supported_response.get("data", [])
        if not supported_coins:
            supported_coins = supported_response if isinstance(supported_response, list) else []
    except Exception as e:
        logger.error(f"Error fetching supported coins: {e}")
        return None

    total_coins = len(supported_coins)
    logger.info(f"Total coins with unlock data on DropStab: {total_coins}")

    # Count unlocks for each coin
    total_unlock_events = 0
    coins_processed = 0
    coins_with_unlocks = 0
    coin_details = []

    for i, coin in enumerate(supported_coins, 1):
        # Get coin slug
        if isinstance(coin, dict):
            slug = coin.get("slug") or coin.get("coinSlug") or coin.get("name", "").lower()
        else:
            slug = str(coin)

        if not slug:
            continue

        try:
            # Get unlocks for this coin
            unlock_data = api.get_token_unlocks(slug)

            # Count unlock events
            if isinstance(unlock_data, dict):
                data = unlock_data.get("data", {})
                if isinstance(data, dict):
                    unlocks = data.get("tokenUnlocks", [])
                else:
                    unlocks = data if isinstance(data, list) else []
            else:
                unlocks = unlock_data if isinstance(unlock_data, list) else []

            event_count = len(unlocks) if unlocks else 0
            total_unlock_events += event_count
            coins_processed += 1

            if event_count > 0:
                coins_with_unlocks += 1

            coin_details.append({
                "slug": slug,
                "unlock_events": event_count
            })

            if i % 50 == 0:
                logger.info(f"Progress: {i}/{total_coins} coins, {total_unlock_events:,} events so far")

        except Exception as e:
            logger.warning(f"Error fetching {slug}: {e}")
            coin_details.append({
                "slug": slug,
                "unlock_events": 0,
                "error": str(e)
            })
            continue

    # Results
    result = {
        "count_date": datetime.now().isoformat(),
        "total_supported_coins": total_coins,
        "coins_processed": coins_processed,
        "coins_with_unlocks": coins_with_unlocks,
        "total_unlock_events": total_unlock_events,
        "coin_details": coin_details
    }

    # Save results
    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved detailed results to: {output_path}")

    # Print summary
    print("\n" + "="*60)
    print("EXACT UNLOCK COUNT ON DROPSTAB")
    print("="*60)
    print(f"Total supported coins:     {total_coins}")
    print(f"Coins processed:           {coins_processed}")
    print(f"Coins with unlock events:  {coins_with_unlocks}")
    print(f"TOTAL UNLOCK EVENTS:       {total_unlock_events:,}")
    print("="*60)

    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Count exact unlock events on DropStab")
    parser.add_argument("--output", "-o", default="unlocks_data/unlock_count.json",
                        help="Output file for detailed results")

    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("DROPSTAB_API_KEY")

    if not api_key:
        print("ERROR: DROPSTAB_API_KEY not found in .env")
        return

    count_all_unlocks(api_key, args.output)


if __name__ == "__main__":
    main()
