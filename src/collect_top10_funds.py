#!/usr/bin/env python3
"""
Collect TOP funds and their new LAUNCHED projects from the last year.

Categories:
- TOP 10 Retail ROI (funds)
- TOP 10 Private ROI (funds)
- TOP 5 Angels by Private ROI

Uses /fundingRounds endpoint with investorSlug filter to get projects by date.
Only includes projects that are already launched (have price/market cap).
"""

import os
import sys
import json
import csv
import logging
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from api_client import DropStabAPI

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# Hardcoded TOP investor lists (from DropStab website, API sorting is broken)
# These are verified real investors with actual investments

TOP_RETAIL_ROI = [
    "bitmain",
    "idg-capital",
    "8-decimal-capital",
    "jump-trading",
    "coinshares",
    "ubik-capital",
    "fundamental-labs",
    "reciprocal-ventures",
    "rockaway-blockchain-fund",  # Rockaway X Low Ventures
    "collabcurrency",
]

TOP_PRIVATE_ROI = [
    "reciprocal-ventures",
    "jump-crypto",
    "fj-syndicates",
    "limitless-crypto-investments",
    "btx-capital",
    "egirl-capital",
    "multicoin-capital",
    "lightspeed-venture-partners",
    "polychain-capital",
    "slow-ventures",
]

TOP_ANGELS = [
    "fred-ehrsam",
    "balaji-srinivasan",
    "naval-ravikant",
    "richard-ma-quantstamp",
    "stani-kulechov",
]

# Categories configuration
CATEGORIES = [
    {
        "name": "TOP 10 Retail ROI",
        "investors": TOP_RETAIL_ROI,
        "output_prefix": "top10_retail_roi"
    },
    {
        "name": "TOP 10 Private ROI",
        "investors": TOP_PRIVATE_ROI,
        "output_prefix": "top10_private_roi"
    },
    {
        "name": "TOP 5 Angels",
        "investors": TOP_ANGELS,
        "output_prefix": "top5_angels"
    }
]


def is_project_launched(coin_data: dict) -> bool:
    """Check if project is launched (trading=CURRENTLY_TRADING or has price > 0)."""
    # Check trading status
    trading = coin_data.get("trading", "")
    if trading == "CURRENTLY_TRADING":
        return True

    # Check price
    price = coin_data.get("price", {})
    if isinstance(price, dict):
        price_usd = price.get("USD", 0) or price.get("usd", 0)
    else:
        price_usd = price or 0

    return bool(price_usd and price_usd > 0)


def get_fund_rounds_in_period(api: DropStabAPI, investor_slug: str, date_from_str: str) -> list:
    """
    Get all funding rounds for an investor from a specific date.

    Uses /fundingRounds endpoint with investorSlug filter.
    """
    all_rounds = []
    page = 0
    max_pages = 20

    while page < max_pages:
        try:
            result = api.get_funding_rounds(
                page=page,
                page_size=100,
                investor_slug=investor_slug
            )

            data = result.get("data", {})
            content = data.get("content", []) if isinstance(data, dict) else []

            if not content:
                break

            # Filter by date
            for round_info in content:
                round_date = round_info.get("date", "")
                if round_date:
                    # Parse date (format: 2024-01-15T00:00:00Z)
                    date_part = round_date.split("T")[0]
                    if date_part >= date_from_str:
                        all_rounds.append(round_info)

            total_pages = data.get("totalPages", 1) if isinstance(data, dict) else 1
            if page + 1 >= total_pages:
                break

            page += 1

        except Exception as e:
            logger.warning(f"Error fetching rounds for {investor_slug}: {e}")
            break

    return all_rounds


def collect_category_data(api: DropStabAPI, category: dict, one_year_ago_str: str, output_path: Path):
    """Collect data for a single category."""
    cat_name = category["name"]
    investor_slugs = category["investors"]
    output_prefix = category["output_prefix"]

    logger.info(f"\n{'='*60}")
    logger.info(f"Processing: {cat_name}")
    logger.info(f"{'='*60}")

    # Statistics
    stats = {
        "category": cat_name,
        "funds_to_process": len(investor_slugs),
        "funds_processed": 0,
        "funds_with_errors": 0,
        "total_rounds_found": 0,
        "rounds_in_period": 0,
        "unique_projects": 0,
        "launched_projects": 0,
        "not_launched_skipped": 0,
        "projects_fetched": 0,
        "projects_with_errors": 0,
    }

    # === Step 1: Get fund details for each investor ===
    logger.info(f"Fetching {len(investor_slugs)} investors...")

    top_funds = []
    for slug in investor_slugs:
        try:
            result = api.get_investor(slug)
            fund_data = result.get("data", {})
            if fund_data:
                top_funds.append(fund_data)
                logger.info(f"  ✓ {fund_data.get('name', slug)}")
            else:
                logger.warning(f"  ✗ {slug} - not found")
        except Exception as e:
            logger.warning(f"  ✗ {slug} - {e}")

    if not top_funds:
        logger.warning(f"No funds found for {cat_name}")
        return None, stats

    logger.info(f"Loaded {len(top_funds)} funds")

    # === Step 2: Get funding rounds for each fund ===
    logger.info("\nFetching funding rounds for each fund...")

    all_projects = {}  # coinSlug -> project info
    project_funds = defaultdict(list)  # coinSlug -> list of funds
    project_rounds = defaultdict(list)  # coinSlug -> list of rounds

    for fund in top_funds:
        fund_slug = fund.get("investorSlug", "")
        fund_name = fund.get("name", "Unknown")

        if not fund_slug:
            continue

        logger.info(f"Processing fund: {fund_name} ({fund_slug})")

        try:
            # Get rounds for this fund in the period
            rounds = get_fund_rounds_in_period(api, fund_slug, one_year_ago_str)
            stats["funds_processed"] += 1
            stats["rounds_in_period"] += len(rounds)

            logger.info(f"  Found {len(rounds)} rounds in period")

            for round_info in rounds:
                coin_slug = round_info.get("coinSlug", "")
                if not coin_slug:
                    continue

                # Add project
                if coin_slug not in all_projects:
                    all_projects[coin_slug] = {
                        "slug": coin_slug,
                        "symbol": round_info.get("coinSymbol", ""),
                        "category": round_info.get("category", ""),
                    }

                # Track which funds invested
                project_funds[coin_slug].append({
                    "fund_slug": fund_slug,
                    "fund_name": fund_name,
                    "round_date": round_info.get("date", ""),
                    "round_stage": round_info.get("stage", ""),
                    "funds_raised": round_info.get("fundsRaised", 0),
                    "pre_valuation": round_info.get("preValuation", 0),
                })

                # Save round info
                project_rounds[coin_slug].append(round_info)

        except Exception as e:
            logger.warning(f"Error processing {fund_name}: {e}")
            stats["funds_with_errors"] += 1
            continue

    stats["unique_projects"] = len(all_projects)
    logger.info(f"\nFound {len(all_projects)} unique projects in period")

    # === Step 3: Get detailed info for launched projects ===
    logger.info("\nFetching detailed project info (only launched)...")

    projects_data = []

    for i, (slug, project) in enumerate(all_projects.items(), 1):
        try:
            coin_detail = api.get_coin_detailed(slug)
            coin_data = coin_detail.get("data", {})

            # Check if launched
            if not is_project_launched(coin_data):
                stats["not_launched_skipped"] += 1
                logger.debug(f"  Skipping {slug} - not launched")
                continue

            stats["launched_projects"] += 1

            # Extract data
            price_obj = coin_data.get("price", {})
            market_cap_obj = coin_data.get("marketCap", {})
            volume_obj = coin_data.get("volume", {})
            change_obj = coin_data.get("change", {})
            ico_price_obj = coin_data.get("icoPrice", {})
            xfrom_ico = coin_data.get("xfromIco", {})

            # Get price values
            if isinstance(price_obj, dict):
                price_usd = price_obj.get("USD", 0) or 0
            else:
                price_usd = price_obj or 0

            if isinstance(market_cap_obj, dict):
                market_cap_usd = market_cap_obj.get("USD", 0) or 0
            else:
                market_cap_usd = market_cap_obj or 0

            if isinstance(volume_obj, dict):
                volume_24h = volume_obj.get("h24", {}).get("USD", 0) or 0
            else:
                volume_24h = 0

            if isinstance(change_obj, dict):
                change_24h = change_obj.get("h24", {}).get("USD", 0) or 0
                change_7d = change_obj.get("d7", {}).get("USD", 0) or 0
            else:
                change_24h = 0
                change_7d = 0

            if isinstance(ico_price_obj, dict):
                ico_price_usd = ico_price_obj.get("USD", 0) or 0
            else:
                ico_price_usd = ico_price_obj or 0

            if isinstance(xfrom_ico, dict):
                ico_roi = xfrom_ico.get("USD", 0) or 0
            else:
                ico_roi = xfrom_ico or 0

            # Get all investors from rounds
            all_investors = set()
            for round_info in project_rounds.get(slug, []):
                for inv in round_info.get("investors", []):
                    inv_name = inv.get("name", "")
                    if inv_name:
                        all_investors.add(inv_name)

            # Get total raised from rounds
            total_raised = sum(r.get("fundsRaised", 0) or 0 for r in project_rounds.get(slug, []))

            project_info = {
                "slug": slug,
                "name": coin_data.get("name", ""),
                "symbol": coin_data.get("symbol", project.get("symbol", "")),
                "category": coin_data.get("mainCategory", {}).get("name", "") or project.get("category", ""),
                "trading": coin_data.get("trading", ""),

                # Market data
                "price_usd": price_usd,
                "market_cap_usd": market_cap_usd,
                "volume_24h_usd": volume_24h,
                "price_change_24h": change_24h,
                "price_change_7d": change_7d,

                # Fundraising data
                "total_raised_usd": total_raised,
                "ico_price_usd": ico_price_usd,
                "ico_roi": ico_roi,

                # Funds from our TOP list
                "top_funds": project_funds.get(slug, []),
                "top_funds_count": len(project_funds.get(slug, [])),
                "top_fund_names": ", ".join(set(f["fund_name"] for f in project_funds.get(slug, []))),

                # ALL investors
                "all_investors_count": len(all_investors),
                "all_investor_names": ", ".join(list(all_investors)[:20]),
            }

            projects_data.append(project_info)
            stats["projects_fetched"] += 1

            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(all_projects)}, {stats['launched_projects']} launched")

        except Exception as e:
            logger.warning(f"Error fetching {slug}: {e}")
            stats["projects_with_errors"] += 1
            continue

    # === Step 4: Save results ===
    logger.info(f"\nSaving results for {cat_name}...")

    # Save JSON
    with open(output_path / f"{output_prefix}_projects.json", 'w', encoding='utf-8') as f:
        json.dump(projects_data, f, indent=2, ensure_ascii=False)

    with open(output_path / f"{output_prefix}_funds.json", 'w', encoding='utf-8') as f:
        json.dump(top_funds, f, indent=2, ensure_ascii=False)

    # Save CSV
    csv_file = output_path / f"{output_prefix}_projects.csv"
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'project_slug', 'project_name', 'symbol', 'category', 'trading',
            'price_usd', 'market_cap_usd', 'volume_24h_usd',
            'price_change_24h', 'price_change_7d',
            'total_raised_usd', 'ico_price_usd', 'ico_roi',
            'top_funds_count', 'top_fund_names',
            'all_investors_count', 'all_investor_names'
        ])

        # Sort by market cap
        projects_sorted = sorted(projects_data, key=lambda x: x.get("market_cap_usd", 0) or 0, reverse=True)

        for p in projects_sorted:
            writer.writerow([
                p.get("slug", ""),
                p.get("name", ""),
                p.get("symbol", ""),
                p.get("category", ""),
                p.get("trading", ""),
                p.get("price_usd", 0),
                p.get("market_cap_usd", 0),
                p.get("volume_24h_usd", 0),
                p.get("price_change_24h", 0),
                p.get("price_change_7d", 0),
                p.get("total_raised_usd", 0),
                p.get("ico_price_usd", 0),
                p.get("ico_roi", 0),
                p.get("top_funds_count", 0),
                p.get("top_fund_names", ""),
                p.get("all_investors_count", 0),
                p.get("all_investor_names", "")
            ])

    # Save stats
    with open(output_path / f"{output_prefix}_stats.json", 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    return projects_data, stats


def collect_all_categories(api_key: str, output_dir: str = "top_funds_analysis"):
    """Collect data for all categories."""
    api = DropStabAPI(api_key)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Date 1 year ago
    one_year_ago = datetime.now() - timedelta(days=365)
    one_year_ago_str = one_year_ago.strftime("%Y-%m-%d")
    logger.info(f"Analyzing projects from: {one_year_ago_str}")

    all_stats = []

    for category in CATEGORIES:
        projects, stats = collect_category_data(api, category, one_year_ago_str, output_path)
        if stats:
            all_stats.append(stats)

    # Print summary
    print("\n" + "="*70)
    print("FINAL SUMMARY - ALL CATEGORIES")
    print("="*70)

    for stats in all_stats:
        print(f"\n📊 {stats['category']}:")
        print("-"*50)
        print(f"  Funds processed:            {stats['funds_processed']}/{stats['funds_to_process']}")
        print(f"  Funds with errors:          {stats['funds_with_errors']}")
        print(f"  Rounds in period:           {stats['rounds_in_period']}")
        print(f"  Unique projects:            {stats['unique_projects']}")
        print(f"  Launched (trading):         {stats['launched_projects']}")
        print(f"  Not launched (skipped):     {stats['not_launched_skipped']}")
        print(f"  Projects fetched:           {stats['projects_fetched']}")
        print(f"  Projects with errors:       {stats['projects_with_errors']}")

        if stats['funds_with_errors'] == 0 and stats['projects_with_errors'] == 0:
            print("  ✅ ALL DATA COLLECTED SUCCESSFULLY")
        else:
            print(f"  ⚠️  SOME ERRORS OCCURRED")

    print(f"\n📁 Output: {output_path}/")
    print("="*70)

    with open(output_path / "all_categories_stats.json", 'w', encoding='utf-8') as f:
        json.dump(all_stats, f, indent=2, ensure_ascii=False)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Collect TOP funds new launched projects")
    parser.add_argument("--output", "-o", default="top_funds_analysis", help="Output directory")

    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("DROPSTAB_API_KEY")

    if not api_key:
        print("ERROR: DROPSTAB_API_KEY not found in .env")
        return

    collect_all_categories(api_key, args.output)


if __name__ == "__main__":
    main()
