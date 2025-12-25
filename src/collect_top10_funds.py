#!/usr/bin/env python3
"""
Collect TOP 10 funds and their new projects from the last year.

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


def collect_top10_funds_data(api_key: str, output_dir: str = "top10_funds_data"):
    """
    Collect TOP 10 funds and their new projects (last 1 year).

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
    logger.info(f"Collecting projects from: {one_year_ago_str}")

    # === Step 1: Get TOP 10 funds by retail ROI ===
    logger.info("Fetching TOP 10 funds...")

    all_funds = api.get_all_investors(sort_by="RETAIL_ROI_PERCENT", sort_order="DESC", max_pages=1)
    top10_funds = all_funds[:10]

    logger.info(f"TOP 10 funds:")
    for i, fund in enumerate(top10_funds, 1):
        name = fund.get("name", "Unknown")
        roi = fund.get("retailRoiPercent", 0)
        logger.info(f"  {i}. {name} (ROI: {roi:.1f}%)")

    # Save fund list
    with open(output_path / "top10_funds.json", 'w', encoding='utf-8') as f:
        json.dump(top10_funds, f, indent=2, ensure_ascii=False)

    # === Step 2: Get detailed info for each fund ===
    logger.info("\nFetching detailed fund portfolios...")

    fund_details = []
    all_projects = {}  # slug -> project data
    project_funds = defaultdict(list)  # slug -> list of funds that invested

    for fund in top10_funds:
        fund_slug = fund.get("slug", "")
        fund_name = fund.get("name", "Unknown")

        if not fund_slug:
            continue

        logger.info(f"Processing fund: {fund_name}")

        try:
            detail = api.get_investor(fund_slug)
            fund_data = detail.get("data", {})
            fund_details.append(fund_data)

            # Get portfolio projects
            portfolio = fund_data.get("portfolio", [])
            logger.info(f"  Portfolio: {len(portfolio)} projects")

            for project in portfolio:
                coin_slug = project.get("coinSlug", "")
                if not coin_slug:
                    continue

                # Check if project is from last year (by funding date)
                funding_rounds = project.get("fundingRounds", [])

                # Get the earliest round date for this fund's investment
                fund_round_dates = []
                for fr in funding_rounds:
                    date_str = fr.get("date", "")
                    if date_str:
                        fund_round_dates.append(date_str)

                if fund_round_dates:
                    earliest_date = min(fund_round_dates)
                    # Check if this fund invested in the last year
                    if earliest_date >= one_year_ago_str:
                        # This is a new investment from last year
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
            continue

    logger.info(f"\nFound {len(all_projects)} new projects (invested in last year)")

    # === Step 3: Get detailed info for each project ===
    logger.info("\nFetching detailed project info...")

    projects_data = []

    for i, (slug, project) in enumerate(all_projects.items(), 1):
        try:
            coin_detail = api.get_coin_detailed(slug)
            coin_data = coin_detail.get("data", {})

            # Extract key metrics
            market_data = coin_data.get("marketData", {})
            fundraising = coin_data.get("fundraising", {})

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

                # Funds that invested
                "funds": project_funds.get(slug, []),
                "funds_count": len(project_funds.get(slug, [])),
                "fund_names": ", ".join([f["fund_name"] for f in project_funds.get(slug, [])])
            }

            projects_data.append(project_info)

            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(all_projects)} projects")

        except Exception as e:
            logger.warning(f"Error fetching {slug}: {e}")
            continue

    # === Step 4: Save results ===
    logger.info("\nSaving results...")

    # Save raw JSON
    with open(output_path / "projects_raw.json", 'w', encoding='utf-8') as f:
        json.dump(projects_data, f, indent=2, ensure_ascii=False)

    # Save CSV summary
    csv_file = output_path / "top10_funds_new_projects.csv"
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'project_slug', 'project_name', 'symbol', 'category',
            'price_usd', 'market_cap_usd', 'volume_24h_usd',
            'price_change_24h', 'price_change_7d',
            'total_raised_usd', 'ico_price_usd', 'ico_roi',
            'funds_count', 'fund_names'
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
                p.get("funds_count", 0),
                p.get("fund_names", "")
            ])

    logger.info(f"Saved {len(projects_data)} projects to {csv_file}")

    # Print summary
    print("\n" + "="*70)
    print("TOP 10 FUNDS - NEW PROJECTS (LAST 1 YEAR)")
    print("="*70)
    print(f"Total new projects: {len(projects_data)}")
    print(f"\nTOP 10 funds analyzed:")
    for i, fund in enumerate(top10_funds, 1):
        print(f"  {i}. {fund.get('name', 'Unknown')}")

    print(f"\nOutput files:")
    print(f"  - {output_path / 'top10_funds.json'}")
    print(f"  - {output_path / 'projects_raw.json'}")
    print(f"  - {csv_file}")
    print("="*70)

    return projects_data


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Collect TOP 10 funds new projects")
    parser.add_argument("--output", "-o", default="top10_funds_data",
                        help="Output directory")

    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("DROPSTAB_API_KEY")

    if not api_key:
        print("ERROR: DROPSTAB_API_KEY not found in .env")
        return

    collect_top10_funds_data(api_key, args.output)


if __name__ == "__main__":
    main()
