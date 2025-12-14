#!/usr/bin/env python3
"""
Token Unlocks Collector - collects unlock/vesting data for top coins.

Output columns:
- coin_symbol, coin_name
- total_supply (max supply)
- circulating_supply
- unlock_1_date, unlock_1_amount, unlock_2_date, unlock_2_amount, ...
"""

import json
import csv
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
import requests
from dotenv import load_dotenv


class UnlocksCollector:
    """Collects token unlock data from DropStab API."""

    BASE_URL = "https://public-api.dropstab.com/api/v1"

    def __init__(self, api_key: str, output_dir: str = "unlocks_data"):
        self.api_key = api_key
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "raw").mkdir(exist_ok=True)

        self.session = requests.Session()
        self.session.headers.update({
            "accept": "*/*",
            "x-dropstab-api-key": api_key,
        })

        self.supported_coins = []
        self.unlocks_data = {}

    def _request(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Make API request with rate limiting."""
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                print(f"Rate limited, waiting 60s...")
                time.sleep(60)
                return self._request(endpoint, params)
            else:
                print(f"API error {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            print(f"Request error: {e}")
            return None

    def get_supported_coins(self, max_coins: int = 2000) -> list:
        """Get list of coins with unlock data available."""
        print(f"Fetching supported coins (max {max_coins})...")
        all_coins = []
        page = 0
        page_size = 100

        while len(all_coins) < max_coins:
            data = self._request("tokenUnlocks/supportedCoins", {
                "page": page,
                "pageSize": page_size
            })

            if not data or data.get('failure'):
                break

            content = data.get('data', {}).get('content', [])
            if not content:
                break

            all_coins.extend(content)
            total = data.get('data', {}).get('totalSize', 0)
            print(f"  Page {page}: got {len(content)} coins (total: {len(all_coins)}/{total})")

            if len(all_coins) >= total or len(all_coins) >= max_coins:
                break

            page += 1
            time.sleep(0.3)  # Rate limiting

        self.supported_coins = all_coins[:max_coins]
        print(f"Total supported coins: {len(self.supported_coins)}")
        return self.supported_coins

    def get_coin_unlocks(self, coin_slug: str) -> Optional[dict]:
        """Get detailed unlock info for a specific coin."""
        # Get future unlocks
        data = self._request(f"tokenUnlocks/{coin_slug}", {
            "unlocksTimelineFilter": "FUTURE",
            "unlocksDateSortOrder": "ASC"
        })

        if not data or data.get('failure'):
            return None

        return data.get('data')

    def collect_all_unlocks(self, max_coins: int = 2000) -> dict:
        """Collect unlock data for all supported coins."""
        if not self.supported_coins:
            self.get_supported_coins(max_coins)

        print(f"\nCollecting unlock details for {len(self.supported_coins)} coins...")

        for i, coin in enumerate(self.supported_coins):
            slug = coin.get('coinSlug')
            symbol = coin.get('coinSymbol')

            if i % 50 == 0:
                print(f"  Progress: {i}/{len(self.supported_coins)} ({symbol})")

            unlocks = self.get_coin_unlocks(slug)
            if unlocks:
                self.unlocks_data[slug] = unlocks

            time.sleep(0.2)  # Rate limiting

        print(f"Collected unlock data for {len(self.unlocks_data)} coins")

        # Save raw data
        raw_path = self.output_dir / "raw" / "unlocks_raw.json"
        with open(raw_path, 'w', encoding='utf-8') as f:
            json.dump(self.unlocks_data, f, indent=2, ensure_ascii=False)
        print(f"Saved raw data: {raw_path}")

        return self.unlocks_data

    def export_to_csv(self, output_name: str = "unlocks_table.csv", max_unlock_cols: int = 50):
        """Export unlock data to CSV with dynamic columns for unlock events."""
        if not self.unlocks_data:
            print("No data to export")
            return

        # First pass: find max number of unlocks across all coins
        max_unlocks_found = 0
        for slug, data in self.unlocks_data.items():
            unlocks = data.get('tokenUnlocks', [])
            if len(unlocks) > max_unlocks_found:
                max_unlocks_found = len(unlocks)

        # Limit columns to prevent memory issues
        max_unlocks = min(max_unlocks_found, max_unlock_cols)
        print(f"Max unlock events found: {max_unlocks_found}, limiting to {max_unlocks} columns")

        # Build header
        header = [
            'coin_slug', 'coin_symbol', 'price_usd', 'market_cap', 'fdv',
            'total_supply', 'circulating_supply', 'circulating_pct',
            'unlocked_pct', 'locked_pct', 'tge_date'
        ]

        # Add dynamic columns for each unlock event
        for i in range(1, max_unlocks + 1):
            header.extend([
                f'unlock_{i}_date',
                f'unlock_{i}_amount',
                f'unlock_{i}_usd',
                f'unlock_{i}_pct',
                f'unlock_{i}_allocation'
            ])

        # Build rows
        rows = []
        for slug, data in self.unlocks_data.items():
            row = {
                'coin_slug': slug,
                'coin_symbol': data.get('coinSymbol', ''),
                'price_usd': data.get('priceUsd', ''),
                'market_cap': data.get('marketCap', ''),
                'fdv': data.get('fdv', ''),
                'circulating_pct': data.get('circulationSupplyPercent', ''),
                'unlocked_pct': data.get('totalTokensUnlockedPercent', ''),
                'locked_pct': data.get('totalTokensLockedPercent', ''),
                'tge_date': data.get('tgeDate', '')[:10] if data.get('tgeDate') else ''
            }

            # Calculate supplies from percentages and FDV/price
            fdv = data.get('fdv')
            price = data.get('priceUsd')
            circ_pct = data.get('circulationSupplyPercent')

            if fdv and price and price > 0:
                total_supply = fdv / price
                row['total_supply'] = total_supply
                if circ_pct:
                    row['circulating_supply'] = total_supply * circ_pct / 100
                else:
                    row['circulating_supply'] = ''
            else:
                row['total_supply'] = ''
                row['circulating_supply'] = ''

            # Add unlock events (limited to max_unlocks)
            unlocks = data.get('tokenUnlocks', [])[:max_unlocks]
            for i, unlock in enumerate(unlocks, 1):
                row[f'unlock_{i}_date'] = unlock.get('date', '')[:10] if unlock.get('date') else ''
                row[f'unlock_{i}_amount'] = unlock.get('tokensAmount', '')
                row[f'unlock_{i}_usd'] = unlock.get('usdAmount', '')
                row[f'unlock_{i}_pct'] = unlock.get('allTokensSharePercent', '')
                row[f'unlock_{i}_allocation'] = unlock.get('allocationName', '')

            # Fill remaining unlock columns with empty
            for i in range(len(unlocks) + 1, max_unlocks + 1):
                row[f'unlock_{i}_date'] = ''
                row[f'unlock_{i}_amount'] = ''
                row[f'unlock_{i}_usd'] = ''
                row[f'unlock_{i}_pct'] = ''
                row[f'unlock_{i}_allocation'] = ''

            rows.append(row)

        # Sort by market cap descending
        rows.sort(key=lambda x: float(x['market_cap']) if x['market_cap'] else 0, reverse=True)

        # Write CSV
        csv_path = self.output_dir / output_name
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)

        print(f"Saved CSV: {csv_path}")

        # Also save summary JSON
        json_path = self.output_dir / "unlocks_summary.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        print(f"Saved JSON: {json_path}")

        return csv_path

    def export_long_format(self, output_name: str = "unlocks_long.csv"):
        """Export unlock data in long format - one row per unlock event."""
        if not self.unlocks_data:
            print("No data to export")
            return

        header = [
            'coin_slug', 'coin_symbol', 'price_usd', 'market_cap', 'fdv',
            'total_supply', 'circulating_supply', 'circulating_pct',
            'unlocked_pct', 'locked_pct',
            'unlock_date', 'unlock_amount', 'unlock_usd', 'unlock_pct', 'allocation'
        ]

        rows = []
        for slug, data in self.unlocks_data.items():
            # Base coin info
            fdv = data.get('fdv')
            price = data.get('priceUsd')
            circ_pct = data.get('circulationSupplyPercent')

            total_supply = ''
            circ_supply = ''
            if fdv and price and price > 0:
                total_supply = fdv / price
                if circ_pct:
                    circ_supply = total_supply * circ_pct / 100

            base = {
                'coin_slug': slug,
                'coin_symbol': data.get('coinSymbol', ''),
                'price_usd': data.get('priceUsd', ''),
                'market_cap': data.get('marketCap', ''),
                'fdv': fdv or '',
                'total_supply': total_supply,
                'circulating_supply': circ_supply,
                'circulating_pct': circ_pct or '',
                'unlocked_pct': data.get('totalTokensUnlockedPercent', ''),
                'locked_pct': data.get('totalTokensLockedPercent', ''),
            }

            # Add row for each unlock event
            unlocks = data.get('tokenUnlocks', [])
            for unlock in unlocks:
                row = base.copy()
                row['unlock_date'] = unlock.get('date', '')[:10] if unlock.get('date') else ''
                row['unlock_amount'] = unlock.get('tokensAmount', '')
                row['unlock_usd'] = unlock.get('usdAmount', '')
                row['unlock_pct'] = unlock.get('allTokensSharePercent', '')
                row['allocation'] = unlock.get('allocationName', '')
                rows.append(row)

        # Sort by market cap then by unlock date
        rows.sort(key=lambda x: (
            -(float(x['market_cap']) if x['market_cap'] else 0),
            x['unlock_date']
        ))

        csv_path = self.output_dir / output_name
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)

        print(f"Saved long format CSV: {csv_path} ({len(rows)} unlock events)")
        return csv_path


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Collect token unlock data")
    parser.add_argument("command", choices=["test", "collect", "export"],
                        help="test=test API, collect=collect data, export=export from cache")
    parser.add_argument("--max-coins", type=int, default=2000, help="Max coins to collect")
    parser.add_argument("--output-dir", default="unlocks_data", help="Output directory")

    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("DROPSTAB_API_KEY")
    if not api_key:
        print("ERROR: DROPSTAB_API_KEY not found in .env")
        return

    collector = UnlocksCollector(api_key, args.output_dir)

    if args.command == "test":
        # Test API connection
        print("Testing API connection...")
        coins = collector.get_supported_coins(max_coins=10)
        if coins:
            print(f"✓ API works! Found {len(coins)} supported coins")
            print(f"  First coin: {coins[0]}")

            # Test getting unlocks for first coin
            slug = coins[0].get('coinSlug')
            unlocks = collector.get_coin_unlocks(slug)
            if unlocks:
                print(f"✓ Got unlock data for {slug}")
                print(f"  Locked: {unlocks.get('totalTokensLockedPercent')}%")
                print(f"  Unlocks count: {len(unlocks.get('tokenUnlocks', []))}")

    elif args.command == "collect":
        collector.collect_all_unlocks(args.max_coins)
        collector.export_to_csv()
        collector.export_long_format()

    elif args.command == "export":
        # Load from cache
        raw_path = Path(args.output_dir) / "raw" / "unlocks_raw.json"
        if raw_path.exists():
            with open(raw_path, 'r', encoding='utf-8') as f:
                collector.unlocks_data = json.load(f)
            print(f"Loaded {len(collector.unlocks_data)} coins from cache")
            collector.export_to_csv()
            collector.export_long_format()
        else:
            print(f"No cache found at {raw_path}")


if __name__ == "__main__":
    main()
