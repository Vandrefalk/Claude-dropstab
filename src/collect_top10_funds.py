#!/usr/bin/env python3
"""
Collect TOP funds and their new LAUNCHED projects from the last year.

Categories:
- TOP 10 Retail ROI (funds)
- TOP 10 Private ROI (funds)
- TOP 5 Angels by Private ROI

Only includes projects that are already launched (have price/market cap).

For each project collects:
- Market cap
- Investment amounts
- Basic parameters (symbol, category, etc.)
- All funds that invested
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


# Categories configuration
CATEGORIES = [
    {
        "name": "TOP 10 Retail ROI",
        "sort_by": "RETAIL_ROI_PERCENT",
        "limit": 10,
        "investor_type": None,  # All types
        "output_prefix": "top10_retail_roi"
    },
    {
        "name": "TOP 10 Private ROI",
        "sort_by": "PRIVATE_ROI_PERCENT",
        "limit": 10,
        "investor_type": None,
        "output_prefix": "top10_private_roi"
    },
    {
        "name": "TOP 5 Angels by Private ROI",
        "sort_by": "PRIVATE_ROI_PERCENT",
        "limit": 5,
        "investor_type": "ANGEL",  # Filter for angels only
        "output_prefix": "top5_angels_private_roi"
    }
]


def is_project_launched(coin_data: dict) -> bool:
    """
    Check if project is launched (has price and/or market cap).

    Args:
        coin_data: Detailed coin data from API

    Returns:
        True if project is launched
    """
    market_data = coin_data.get("marketData", {})
    if not market_data:
        return False

    price = market_data.get("priceUsd", 0)
    market_cap = market_data.get("marketCapUsd", 0)

    # Project is launched if it has a price > 0 or market cap > 0
    return bool(price and price > 0) or bool(market_cap and market_cap > 0)


def collect_category_data(api: DropStabAPI, category: dict, one_year_ago_str: str, output_path: Path):
    """
    Collect data for a single category.

    Args:
        api: DropStab API client
        category: Category configuration
        one_year_ago_str: Date string for 1 year ago filter
        output_path: Output directory path

    Returns:
        dict with results and stats
    """
    cat_name = category["name"]
    sort_by = category["sort_by"]
    limit = category["limit"]
    investor_type = category.get("investor_type")
    output_prefix = category["output_prefix"]

    logger.info(f"\n{'='*60}")
    logger.info(f"Processing: {cat_name}")
    logger.info(f"{'='*60}")

    # Statistics for verification
    stats = {
        "category": cat_name,
        "funds_to_process": limit,
        "funds_processed": 0,
        "funds_with_errors": 0,
        "total_portfolio_projects": 0,
        "new_projects_in_year": 0,
        "launched_projects": 0,
        "not_launched_skipped": 0,
        "projects_fetched": 0,
        "projects_with_errors": 0,
    }

    # === Step 1: Get funds for this category ===
    logger.info(f"Fetching {limit} funds sorted by {sort_by}...")

    all_funds = api.get_all_investors(sort_by=sort_by, sort_order="DESC", max_pages=5)

    # Filter by investor type if specified
    if investor_type:
        filtered_funds = [f for f in all_funds if f.get("type") == investor_type]
        logger.info(f"Filtered to {len(filtered_funds)} {investor_type} investors")
        top_funds = filtered_funds[:limit]
    else:
        top_funds = all_funds[:limit]

    if not top_funds:
        logger.warning(f"No funds found for {cat_name}")
        return None, stats

    logger.info(f"Selected {len(top_funds)} funds:")
    for i, fund in enumerate(top_funds, 1):
        name = fund.get("name", "Unknown")
        roi_field = "retailRoiPercent" if "RETAIL" in sort_by else "privateRoiPercent"
        roi = fund.get(roi_field, 0) or 0
        fund_type = fund.get("type", "")
        logger.info(f"  {i}. {name} ({fund_type}, ROI: {roi:.1f}%)")

    # === Step 2: Get detailed info for each fund ===
    logger.info("\nFetching detailed fund portfolios...")

    all_projects = {}  # slug -> project data
    project_funds = defaultdict(list)  # slug -> list of funds that invested

    for fund in top_funds:
        fund_slug = fund.get("slug", "")
        fund_name = fund.get("name", "Unknown")

        if not fund_slug:
            continue

        logger.info(f"Processing fund: {fund_name}")

        try:
            detail = api.get_investor(fund_slug)
            fund_data = detail.get("data", {})
            stats["funds_processed"] += 1

            portfolio = fund_data.get("portfolio", [])
            stats["total_portfolio_projects"] += len(portfolio)
            logger.info(f"  Portfolio: {len(portfolio)} projects")

            for project in portfolio:
                coin_slug = project.get("coinSlug", "")
                if not coin_slug:
                    continue

                # Check if project is from last year (by funding date)
                funding_rounds = project.get("fundingRounds", [])

                fund_round_dates = []
                for fr in funding_rounds:
                    date_str = fr.get("date", "")
                    if date_str:
                        fund_round_dates.append(date_str)

                if fund_round_dates:
                    earliest_date = min(fund_round_dates)
                    if earliest_date >= one_year_ago_str:
                        stats["new_projects_in_year"] += 1

                        if coin_slug not in all_projects:
                            all_projects[coin_slug] = {
                                "slug": coin_slug,
                                "name": project.get("coinName", ""),
                                "symbol": project.get("coinSymbol", ""),
                                "first_investment_date": earliest_date
                            }

                        project_funds[coin_slug].append({
                            "fund_slug": fund_slug,
                            "fund_name": fund_name,
                            "investment_date": earliest_date,
                            "rounds": funding_rounds
                        })

        except Exception as e:
            logger.warning(f"Error fetching {fund_name}: {e}")
            stats["funds_with_errors"] += 1
            continue

    logger.info(f"\nFound {len(all_projects)} unique new projects (invested in last year)")

    # === Step 3: Get detailed info for each project (only launched) ===
    logger.info("\nFetching detailed project info (only launched projects)...")

    projects_data = []

    for i, (slug, project) in enumerate(all_projects.items(), 1):
        try:
            coin_detail = api.get_coin_detailed(slug)
            coin_data = coin_detail.get("data", {})

            # Check if project is launched
            if not is_project_launched(coin_data):
                stats["not_launched_skipped"] += 1
                logger.debug(f"  Skipping {slug} - not launched")
                continue

            stats["launched_projects"] += 1

            market_data = coin_data.get("marketData", {})
            fundraising = coin_data.get("fundraising", {})

            # Get ALL investors for this project (not just from our top funds)
            all_investors = fundraising.get("investors", [])
            all_investor_names = [inv.get("name", "") for inv in all_investors if inv.get("name")]

            project_info = {
                "slug": slug,
                "name": coin_data.get("name", project.get("name", "")),
                "symbol": coin_data.get("symbol", project.get("symbol", "")),
                "category": coin_data.get("category", {}).get("name", ""),

                # Market data
                "price_usd": market_data.get("priceUsd", 0),
                "market_cap_usd": market_data.get("marketCapUsd", 0),
                "volume_24h_usd": market_data.get("volume24hUsd", 0),
                "price_change_24h": market_data.get("priceChange24h", 0),
                "price_change_7d": market_data.get("priceChange7d", 0),

                # Fundraising data
                "total_raised_usd": fundraising.get("totalRaisedUsd", 0),
                "ico_price_usd": fundraising.get("icoPriceUsd", 0),
                "ico_roi": fundraising.get("icoRoi", 0),

                # Funds from our TOP list that invested
                "top_funds": project_funds.get(slug, []),
                "top_funds_count": len(project_funds.get(slug, [])),
                "top_fund_names": ", ".join([f["fund_name"] for f in project_funds.get(slug, [])]),

                # ALL investors in this project
                "all_investors_count": len(all_investor_names),
                "all_investor_names": ", ".join(all_investor_names[:20]),  # First 20
            }

            projects_data.append(project_info)
            stats["projects_fetched"] += 1

            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(all_projects)} projects checked, {stats['launched_projects']} launched")

        except Exception as e:
            logger.warning(f"Error fetching {slug}: {e}")
            stats["projects_with_errors"] += 1
            continue

    # === Step 4: Save results ===
    logger.info(f"\nSaving results for {cat_name}...")

    # Save raw JSON
    with open(output_path / f"{output_prefix}_projects.json", 'w', encoding='utf-8') as f:
        json.dump(projects_data, f, indent=2, ensure_ascii=False)

    # Save funds list
    with open(output_path / f"{output_prefix}_funds.json", 'w', encoding='utf-8') as f:
        json.dump(top_funds, f, indent=2, ensure_ascii=False)

    # Save CSV summary
    csv_file = output_path / f"{output_prefix}_projects.csv"
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'project_slug', 'project_name', 'symbol', 'category',
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
    """
    Collect data for all categories.

    Args:
        api_key: DropStab API key
        output_dir: Directory for output files
    """
    api = DropStabAPI(api_key)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Calculate date 1 year ago
    one_year_ago = datetime.now() - timedelta(days=365)
    one_year_ago_str = one_year_ago.strftime("%Y-%m-%d")
    logger.info(f"Analyzing projects from: {one_year_ago_str}")

    all_stats = []

    for category in CATEGORIES:
        projects, stats = collect_category_data(api, category, one_year_ago_str, output_path)
        if stats:
            all_stats.append(stats)

    # === Print final summary ===
    print("\n" + "="*70)
    print("FINAL SUMMARY - ALL CATEGORIES")
    print("="*70)

    for stats in all_stats:
        print(f"\n📊 {stats['category']}:")
        print("-"*50)
        print(f"  Funds to process:           {stats['funds_to_process']}")
        print(f"  Funds processed:            {stats['funds_processed']}")
        print(f"  Funds with errors:          {stats['funds_with_errors']}")
        print(f"  Total portfolio projects:   {stats['total_portfolio_projects']}")
        print(f"  New projects (1 year):      {stats['new_projects_in_year']}")
        print(f"  Launched (with price):      {stats['launched_projects']}")
        print(f"  Not launched (skipped):     {stats['not_launched_skipped']}")
        print(f"  Projects fetched:           {stats['projects_fetched']}")
        print(f"  Projects with errors:       {stats['projects_with_errors']}")

        if stats['funds_with_errors'] == 0 and stats['projects_with_errors'] == 0:
            print("  ✅ ALL DATA COLLECTED SUCCESSFULLY")
        else:
            print(f"  ⚠️  SOME ERRORS OCCURRED")

    print(f"\n📁 Output files saved to: {output_path}/")
    print("="*70)

    # Save combined stats
    with open(output_path / "all_categories_stats.json", 'w', encoding='utf-8') as f:
        json.dump(all_stats, f, indent=2, ensure_ascii=False)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Collect TOP funds new launched projects")
    parser.add_argument("--output", "-o", default="top_funds_analysis",
                        help="Output directory")

    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("DROPSTAB_API_KEY")

    if not api_key:
        print("ERROR: DROPSTAB_API_KEY not found in .env")
        return

    collect_all_categories(api_key, args.output)


if __name__ == "__main__":
    main()
