#!/usr/bin/env python3
"""
Collect TOP funds and ALL their projects from the last year.

Categories:
- TOP 10+ Retail ROI (funds)
- TOP 10 Private ROI (funds)
- TOP 5 Angels
- Additional TOP funds

Collects comprehensive data:
- Market cap, FDV, price
- Circulating/total/max supply
- Locked tokens
- ATH/ATL
- ICO price and rounds
- All investors
- Twitter performance
- Project status (launched/not_launched)
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
    "rockawayx",  # Rockaway X Low Ventures
    "collab-currency",  # Collab+Currency
    "fj-syndicates",
    "signum-capital",
    "limitless-crypto-investments",
    "a16z-andreessen-horowitz",
]

TOP_PRIVATE_ROI = [
    "reciprocal-ventures",
    "jump-crypto",
    "fj-syndicates",
    "limitless-crypto-investments",
    "btx-capital",
]

TOP_ANGELS = [
    "fred-ehrsam",
    "balaji-srinivasan",
    "naval-ravikant",
    "richard-ma-quantstamp",
    "stani-kulechov",
]

ADDITIONAL_TOP = [
    "egirl-capital",
    "multicoin-capital",
    "lightspeed-venture-partners",
    "polychain-capital",
    "slow-ventures",
    "redpoint-ventures",
    "mill-city-ventures",
    "blocktower-capital",  # Strobe
    "franklin-templeton",
    "tge-capital",
    "distributed-global",
    "initialized-capital",
]

# Categories configuration
CATEGORIES = [
    {
        "name": "TOP Retail ROI",
        "investors": TOP_RETAIL_ROI,
        "output_prefix": "top_retail_roi"
    },
    {
        "name": "TOP Private ROI",
        "investors": TOP_PRIVATE_ROI,
        "output_prefix": "top_private_roi"
    },
    {
        "name": "TOP 5 Angels",
        "investors": TOP_ANGELS,
        "output_prefix": "top5_angels"
    },
    {
        "name": "Additional TOP Funds",
        "investors": ADDITIONAL_TOP,
        "output_prefix": "additional_top"
    }
]


def is_project_launched(coin_data: dict) -> bool:
    """Check if project is launched (trading=CURRENTLY_TRADING or has price > 0)."""
    trading = coin_data.get("trading", "")
    if trading == "CURRENTLY_TRADING":
        return True

    price = coin_data.get("price", {})
    if isinstance(price, dict):
        price_usd = price.get("USD", 0) or 0
    else:
        price_usd = price or 0

    return bool(price_usd and price_usd > 0)


def get_fund_rounds_in_period(api: DropStabAPI, investor_slug: str, date_from_str: str) -> list:
    """Get all funding rounds for an investor from a specific date."""
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

            for round_info in content:
                round_date = round_info.get("date", "")
                if round_date:
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


def get_token_unlocks_info(api: DropStabAPI, slug: str) -> dict:
    """Get token unlock info for a coin."""
    try:
        result = api.get_token_unlocks(slug)
        data = result.get("data", {})
        return {
            "locked_percent": data.get("totalTokensLockedPercent", 0) or 0,
            "locked_amount": data.get("totalTokensLockedAmount", 0) or 0,
            "unlocked_percent": data.get("totalTokensUnlockedPercent", 0) or 0,
        }
    except:
        return {"locked_percent": 0, "locked_amount": 0, "unlocked_percent": 0}


def extract_usd_value(obj, default=0):
    """Extract USD value from nested object."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get("USD", default) or default
    return obj or default


def collect_category_data(api: DropStabAPI, category: dict, one_year_ago_str: str, one_month_ago_str: str, output_path: Path):
    """Collect data for a single category."""
    cat_name = category["name"]
    investor_slugs = category["investors"]
    output_prefix = category["output_prefix"]

    logger.info(f"\n{'='*60}")
    logger.info(f"Processing: {cat_name}")
    logger.info(f"{'='*60}")

    stats = {
        "category": cat_name,
        "funds_to_process": len(investor_slugs),
        "funds_processed": 0,
        "funds_with_errors": 0,
        "rounds_in_year": 0,
        "rounds_in_month": 0,
        "unique_projects": 0,
        "launched_projects": 0,
        "not_launched_skipped": 0,
        "projects_fetched": 0,
        "projects_with_errors": 0,
    }

    # === Step 1: Get fund details ===
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
                stats["funds_with_errors"] += 1
        except Exception as e:
            logger.warning(f"  ✗ {slug} - {e}")
            stats["funds_with_errors"] += 1

    if not top_funds:
        logger.warning(f"No funds found for {cat_name}")
        return None, stats

    logger.info(f"Loaded {len(top_funds)} funds")

    # === Step 2: Get funding rounds ===
    logger.info("\nFetching funding rounds...")

    all_projects = {}
    project_funds = defaultdict(list)
    project_rounds = defaultdict(list)

    for fund in top_funds:
        fund_slug = fund.get("investorSlug", "")
        fund_name = fund.get("name", "Unknown")

        if not fund_slug:
            continue

        logger.info(f"Processing: {fund_name}")

        try:
            rounds = get_fund_rounds_in_period(api, fund_slug, one_year_ago_str)
            stats["funds_processed"] += 1

            rounds_in_year = len(rounds)
            rounds_in_month = len([r for r in rounds if r.get("date", "")[:10] >= one_month_ago_str])

            stats["rounds_in_year"] += rounds_in_year
            stats["rounds_in_month"] += rounds_in_month

            logger.info(f"  Rounds: {rounds_in_year} (year), {rounds_in_month} (month)")

            for round_info in rounds:
                coin_slug = round_info.get("coinSlug", "")
                if not coin_slug:
                    continue

                if coin_slug not in all_projects:
                    all_projects[coin_slug] = {
                        "slug": coin_slug,
                        "symbol": round_info.get("coinSymbol", ""),
                        "category": round_info.get("category", ""),
                    }

                project_funds[coin_slug].append({
                    "fund_slug": fund_slug,
                    "fund_name": fund_name,
                    "round_date": round_info.get("date", ""),
                    "round_stage": round_info.get("stage", ""),
                    "funds_raised": round_info.get("fundsRaised", 0),
                    "pre_valuation": round_info.get("preValuation", 0),
                })

                project_rounds[coin_slug].append(round_info)

        except Exception as e:
            logger.warning(f"Error: {fund_name} - {e}")
            stats["funds_with_errors"] += 1

    stats["unique_projects"] = len(all_projects)
    logger.info(f"\nFound {len(all_projects)} unique projects")

    # === Step 3: Get detailed project info ===
    logger.info("\nFetching project details (ALL projects)...")

    projects_data = []

    for i, (slug, project) in enumerate(all_projects.items(), 1):
        try:
            coin_detail = api.get_coin_detailed(slug)
            coin_data = coin_detail.get("data", {})

            # Determine project status
            is_launched = is_project_launched(coin_data)
            if is_launched:
                stats["launched_projects"] += 1
            else:
                stats["not_launched_skipped"] += 1  # now tracking, not skipping

            # Get token unlocks
            unlocks = get_token_unlocks_info(api, slug)

            # Extract all values
            price_usd = extract_usd_value(coin_data.get("price"))
            market_cap_usd = extract_usd_value(coin_data.get("marketCap"))
            fdv = coin_data.get("fullyDilutedValuation", 0) or 0
            circulating_supply = coin_data.get("circulatingSupply", 0) or 0
            total_supply = coin_data.get("totalSupply", 0) or 0
            max_supply = coin_data.get("maxSupply", 0)
            if max_supply == -1:
                max_supply = None  # Unlimited

            ath_usd = extract_usd_value(coin_data.get("ath"))
            atl_usd = extract_usd_value(coin_data.get("atl"))
            ico_price_usd = extract_usd_value(coin_data.get("icoPrice"))
            ico_roi = extract_usd_value(coin_data.get("xfromIco"))
            twitter_performance = coin_data.get("twitterPerformance", 0) or 0

            # Volume and change
            volume_obj = coin_data.get("volume", {})
            if isinstance(volume_obj, dict) and "h24" in volume_obj:
                volume_24h = extract_usd_value(volume_obj.get("h24"))
            else:
                volume_24h = 0

            change_obj = coin_data.get("change", {})
            if isinstance(change_obj, dict):
                change_24h = extract_usd_value(change_obj.get("h24"))
                change_7d = extract_usd_value(change_obj.get("d7"))
            else:
                change_24h = 0
                change_7d = 0

            # All investors from rounds
            all_investors = set()
            for round_info in project_rounds.get(slug, []):
                for inv in round_info.get("investors", []):
                    inv_name = inv.get("name", "")
                    if inv_name:
                        all_investors.add(inv_name)

            # Total raised and rounds info
            rounds_list = project_rounds.get(slug, [])
            total_raised = sum(r.get("fundsRaised", 0) or 0 for r in rounds_list)
            rounds_info = "; ".join([
                f"{r.get('stage', 'Unknown')} ({r.get('date', '')[:10]}): ${r.get('fundsRaised', 0):,.0f}"
                for r in rounds_list if r.get('fundsRaised')
            ])

            project_info = {
                "slug": slug,
                "name": coin_data.get("name", ""),
                "symbol": coin_data.get("symbol", project.get("symbol", "")),
                "category": coin_data.get("mainCategory", {}).get("name", "") or project.get("category", ""),
                "trading": coin_data.get("trading", ""),
                "status": "launched" if is_launched else "not_launched",

                # Market data
                "price_usd": price_usd,
                "market_cap_usd": market_cap_usd,
                "fdv": fdv,
                "volume_24h_usd": volume_24h,
                "price_change_24h": change_24h,
                "price_change_7d": change_7d,

                # Supply
                "circulating_supply": circulating_supply,
                "total_supply": total_supply,
                "max_supply": max_supply,

                # Locked tokens
                "locked_percent": unlocks["locked_percent"],
                "locked_amount": unlocks["locked_amount"],
                "unlocked_percent": unlocks["unlocked_percent"],

                # ATH/ATL
                "ath_usd": ath_usd,
                "atl_usd": atl_usd,

                # ICO/Fundraising
                "ico_price_usd": ico_price_usd,
                "ico_roi": ico_roi,
                "total_raised_usd": total_raised,
                "rounds_info": rounds_info,

                # Social
                "twitter_score": twitter_performance,

                # Investors
                "top_funds": project_funds.get(slug, []),
                "top_funds_count": len(project_funds.get(slug, [])),
                "top_fund_names": ", ".join(set(f["fund_name"] for f in project_funds.get(slug, []))),
                "all_investors_count": len(all_investors),
                "all_investor_names": ", ".join(sorted(all_investors)[:30]),
            }

            projects_data.append(project_info)
            stats["projects_fetched"] += 1

            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(all_projects)}, {stats['launched_projects']} launched")

        except Exception as e:
            logger.warning(f"Error: {slug} - {e}")
            stats["projects_with_errors"] += 1

    # === Step 4: Save results ===
    logger.info(f"\nSaving {len(projects_data)} projects...")

    # JSON
    with open(output_path / f"{output_prefix}_projects.json", 'w', encoding='utf-8') as f:
        json.dump(projects_data, f, indent=2, ensure_ascii=False)

    with open(output_path / f"{output_prefix}_funds.json", 'w', encoding='utf-8') as f:
        json.dump(top_funds, f, indent=2, ensure_ascii=False)

    # CSV
    csv_file = output_path / f"{output_prefix}_projects.csv"
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'slug', 'name', 'symbol', 'category', 'status', 'trading',
            'price_usd', 'market_cap_usd', 'fdv', 'volume_24h_usd',
            'change_24h', 'change_7d',
            'circulating_supply', 'total_supply', 'max_supply',
            'locked_percent', 'locked_amount', 'unlocked_percent',
            'ath_usd', 'atl_usd',
            'ico_price_usd', 'ico_roi', 'total_raised_usd', 'rounds_info',
            'twitter_score',
            'top_funds_count', 'top_fund_names',
            'all_investors_count', 'all_investor_names'
        ])

        # Sort: launched first (by market cap), then not_launched (by name)
        launched = [p for p in projects_data if p.get("status") == "launched"]
        not_launched = [p for p in projects_data if p.get("status") != "launched"]
        launched_sorted = sorted(launched, key=lambda x: x.get("market_cap_usd", 0) or 0, reverse=True)
        not_launched_sorted = sorted(not_launched, key=lambda x: x.get("name", "").lower())
        projects_sorted = launched_sorted + not_launched_sorted

        for p in projects_sorted:
            writer.writerow([
                p.get("slug", ""),
                p.get("name", ""),
                p.get("symbol", ""),
                p.get("category", ""),
                p.get("status", ""),
                p.get("trading", ""),
                p.get("price_usd", 0),
                p.get("market_cap_usd", 0),
                p.get("fdv", 0),
                p.get("volume_24h_usd", 0),
                p.get("price_change_24h", 0),
                p.get("price_change_7d", 0),
                p.get("circulating_supply", 0),
                p.get("total_supply", 0),
                p.get("max_supply", ""),
                p.get("locked_percent", 0),
                p.get("locked_amount", 0),
                p.get("unlocked_percent", 0),
                p.get("ath_usd", 0),
                p.get("atl_usd", 0),
                p.get("ico_price_usd", 0),
                p.get("ico_roi", 0),
                p.get("total_raised_usd", 0),
                p.get("rounds_info", ""),
                p.get("twitter_score", 0),
                p.get("top_funds_count", 0),
                p.get("top_fund_names", ""),
                p.get("all_investors_count", 0),
                p.get("all_investor_names", "")
            ])

    with open(output_path / f"{output_prefix}_stats.json", 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    return projects_data, stats


def create_combined_csv(all_projects: list, output_path: Path):
    """Create a combined CSV with all projects from all categories."""
    logger.info(f"\nCreating combined CSV with {len(all_projects)} total projects...")

    # Deduplicate by slug (same project may appear in multiple categories)
    seen_slugs = {}
    for p in all_projects:
        slug = p.get("slug", "")
        if slug not in seen_slugs:
            seen_slugs[slug] = p
        else:
            # Merge categories
            existing_cat = seen_slugs[slug].get("investor_category", "")
            new_cat = p.get("investor_category", "")
            if new_cat and new_cat not in existing_cat:
                seen_slugs[slug]["investor_category"] = f"{existing_cat}; {new_cat}"

    unique_projects = list(seen_slugs.values())

    csv_file = output_path / "all_projects_combined.csv"
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'slug', 'name', 'symbol', 'category', 'investor_category', 'status', 'trading',
            'price_usd', 'market_cap_usd', 'fdv', 'volume_24h_usd',
            'change_24h', 'change_7d',
            'circulating_supply', 'total_supply', 'max_supply',
            'locked_percent', 'locked_amount', 'unlocked_percent',
            'ath_usd', 'atl_usd',
            'ico_price_usd', 'ico_roi', 'total_raised_usd', 'rounds_info',
            'twitter_score',
            'top_funds_count', 'top_fund_names',
            'all_investors_count', 'all_investor_names'
        ])

        # Sort: launched first (by market cap), then not_launched (by name)
        launched = [p for p in unique_projects if p.get("status") == "launched"]
        not_launched = [p for p in unique_projects if p.get("status") != "launched"]
        launched_sorted = sorted(launched, key=lambda x: x.get("market_cap_usd", 0) or 0, reverse=True)
        not_launched_sorted = sorted(not_launched, key=lambda x: x.get("name", "").lower())
        projects_sorted = launched_sorted + not_launched_sorted

        for p in projects_sorted:
            writer.writerow([
                p.get("slug", ""),
                p.get("name", ""),
                p.get("symbol", ""),
                p.get("category", ""),
                p.get("investor_category", ""),
                p.get("status", ""),
                p.get("trading", ""),
                p.get("price_usd", 0),
                p.get("market_cap_usd", 0),
                p.get("fdv", 0),
                p.get("volume_24h_usd", 0),
                p.get("price_change_24h", 0),
                p.get("price_change_7d", 0),
                p.get("circulating_supply", 0),
                p.get("total_supply", 0),
                p.get("max_supply", ""),
                p.get("locked_percent", 0),
                p.get("locked_amount", 0),
                p.get("unlocked_percent", 0),
                p.get("ath_usd", 0),
                p.get("atl_usd", 0),
                p.get("ico_price_usd", 0),
                p.get("ico_roi", 0),
                p.get("total_raised_usd", 0),
                p.get("rounds_info", ""),
                p.get("twitter_score", 0),
                p.get("top_funds_count", 0),
                p.get("top_fund_names", ""),
                p.get("all_investors_count", 0),
                p.get("all_investor_names", "")
            ])

    logger.info(f"Combined CSV saved: {csv_file} ({len(unique_projects)} unique projects)")

    # Also save combined JSON
    json_file = output_path / "all_projects_combined.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(unique_projects, f, indent=2, ensure_ascii=False)


def collect_all_categories(api_key: str, output_dir: str = "top_funds_analysis"):
    """Collect data for all categories."""
    api = DropStabAPI(api_key)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Date filters
    now = datetime.now()
    one_year_ago = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    one_month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    logger.info(f"Date filters: 1 year = {one_year_ago}, 1 month = {one_month_ago}")

    all_stats = []
    all_projects = []  # Combined list for all categories

    for category in CATEGORIES:
        projects, stats = collect_category_data(api, category, one_year_ago, one_month_ago, output_path)
        if stats:
            all_stats.append(stats)
        if projects:
            # Add category info to each project
            for p in projects:
                p["investor_category"] = category["name"]
            all_projects.extend(projects)

    # Create combined CSV with all projects
    if all_projects:
        create_combined_csv(all_projects, output_path)

    # Summary
    print("\n" + "="*70)
    print("FINAL SUMMARY")
    print("="*70)

    for stats in all_stats:
        print(f"\n📊 {stats['category']}:")
        print("-"*50)
        print(f"  Funds: {stats['funds_processed']}/{stats['funds_to_process']} (errors: {stats['funds_with_errors']})")
        print(f"  Rounds: {stats['rounds_in_year']} (year), {stats['rounds_in_month']} (month)")
        print(f"  Projects: {stats['unique_projects']} total ({stats['launched_projects']} launched, {stats['not_launched_skipped']} not launched)")
        print(f"  Fetched: {stats['projects_fetched']} (errors: {stats['projects_with_errors']})")

        if stats['funds_with_errors'] == 0 and stats['projects_with_errors'] == 0:
            print("  ✅ SUCCESS")
        else:
            print("  ⚠️ SOME ERRORS")

    print(f"\n📁 Output: {output_path}/")
    print("="*70)

    with open(output_path / "all_stats.json", 'w', encoding='utf-8') as f:
        json.dump(all_stats, f, indent=2, ensure_ascii=False)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Collect TOP funds projects")
    parser.add_argument("--output", "-o", default="top_funds_analysis", help="Output directory")

    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("DROPSTAB_API_KEY")

    if not api_key:
        print("ERROR: DROPSTAB_API_KEY not found")
        return

    collect_all_categories(api_key, args.output)


if __name__ == "__main__":
    main()
