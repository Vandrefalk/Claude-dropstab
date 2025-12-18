#!/usr/bin/env python3
"""
Extended Data Collection - TOP 50 funds, 4 years of data.

Collects more comprehensive investment data for historical analysis.
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def collect_extended_data(
    api_key: str,
    output_dir: str = "API data/raw_extended",
    top_n_funds: int = 50,
    max_funding_pages: int = 200
):
    """
    Collect extended dataset with more funds and funding rounds.

    Args:
        api_key: DropStab API key
        output_dir: Output directory for raw data
        top_n_funds: Number of top funds to collect (default 50)
        max_funding_pages: Max pages of funding rounds (200 * 100 = 20,000 rounds)
    """
    from api_client import DropStabAPI

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    api = DropStabAPI(api_key)

    def save_json(filename: str, data):
        filepath = output_path / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Saved {filepath}")

    # 1. Collect TOP N investors by retail ROI
    logger.info(f"=== Collecting TOP {top_n_funds} investors ===")

    seen_slugs = set()
    all_investors = []

    # By retail ROI
    logger.info("Fetching by RETAIL_ROI_PERCENT...")
    retail_investors = api.get_all_investors(sort_by="RETAIL_ROI_PERCENT", sort_order="DESC")
    for inv in retail_investors[:top_n_funds]:
        slug = inv.get("investorSlug")
        if slug and slug not in seen_slugs:
            seen_slugs.add(slug)
            all_investors.append(inv)
    logger.info(f"Got {len(all_investors)} unique investors from retail ROI")

    # By private ROI
    logger.info("Fetching by PRIVATE_ROI_PERCENT...")
    private_investors = api.get_all_investors(sort_by="PRIVATE_ROI_PERCENT", sort_order="DESC")
    for inv in private_investors[:top_n_funds]:
        slug = inv.get("investorSlug")
        if slug and slug not in seen_slugs:
            seen_slugs.add(slug)
            all_investors.append(inv)
    logger.info(f"Total unique investors: {len(all_investors)}")

    save_json("top_investors.json", all_investors)

    # 2. Collect all funding rounds (more pages)
    logger.info(f"=== Collecting funding rounds (max {max_funding_pages} pages) ===")

    all_rounds = []
    page = 0

    while page < max_funding_pages:
        try:
            result = api.get_funding_rounds(page=page, page_size=100)
            data = result.get("data", {})
            content = data.get("content", []) if isinstance(data, dict) else []

            if not content:
                logger.info(f"No more data at page {page}")
                break

            all_rounds.extend(content)

            total_pages = data.get("totalPages", 1) if isinstance(data, dict) else 1
            if page % 20 == 0:
                logger.info(f"Page {page}/{total_pages}: {len(all_rounds)} rounds collected")

            if page + 1 >= total_pages:
                logger.info(f"Reached last page: {total_pages}")
                break

            page += 1

        except Exception as e:
            logger.error(f"Error at page {page}: {e}")
            break

    logger.info(f"Total funding rounds: {len(all_rounds)}")
    save_json("funding_rounds_raw.json", all_rounds)

    # 3. Extract unique coins
    logger.info("=== Extracting unique coins ===")
    coin_slugs = set()
    for round_data in all_rounds:
        slug = round_data.get("coinSlug")
        if slug:
            coin_slugs.add(slug)

    logger.info(f"Found {len(coin_slugs)} unique coins")

    # 4. Collect coin details
    logger.info("=== Collecting coin details ===")
    coin_details = {}
    coin_slugs_list = list(coin_slugs)

    for i, slug in enumerate(coin_slugs_list, 1):
        try:
            if i % 100 == 0:
                logger.info(f"Progress: {i}/{len(coin_slugs_list)}")
            coin_details[slug] = api.get_coin_detailed(slug)
        except Exception as e:
            logger.error(f"Error fetching {slug}: {e}")
            continue

    logger.info(f"Collected details for {len(coin_details)} coins")
    save_json("coin_details.json", coin_details)

    # 5. Collect investor details
    logger.info("=== Collecting investor details ===")
    investor_details = {}
    investor_slugs = [inv.get("investorSlug") for inv in all_investors if inv.get("investorSlug")]

    for i, slug in enumerate(investor_slugs, 1):
        try:
            logger.info(f"[{i}/{len(investor_slugs)}] Fetching {slug}...")
            investor_details[slug] = api.get_investor(slug)
        except Exception as e:
            logger.error(f"Error fetching {slug}: {e}")
            continue

    save_json("investor_details.json", investor_details)

    # Summary
    summary = {
        "collection_date": datetime.now().isoformat(),
        "top_n_funds": top_n_funds,
        "total_investors": len(all_investors),
        "total_funding_rounds": len(all_rounds),
        "unique_coins": len(coin_slugs),
        "coins_with_details": len(coin_details),
    }
    save_json("collection_summary.json", summary)

    logger.info("=" * 60)
    logger.info("Collection complete!")
    logger.info(f"Investors: {len(all_investors)}")
    logger.info(f"Funding rounds: {len(all_rounds)}")
    logger.info(f"Unique coins: {len(coin_slugs)}")
    logger.info(f"Data saved to: {output_path}")

    return summary


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Extended data collection for investment analysis")
    parser.add_argument("--output-dir", default="API data/raw_extended", help="Output directory")
    parser.add_argument("--top-funds", type=int, default=50, help="Number of top funds (default 50)")
    parser.add_argument("--max-pages", type=int, default=200, help="Max funding round pages (default 200 = 20k rounds)")

    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("DROPSTAB_API_KEY")

    if not api_key:
        print("ERROR: DROPSTAB_API_KEY not found in .env")
        print("Create .env file with: DROPSTAB_API_KEY=your-key-here")
        return

    collect_extended_data(
        api_key=api_key,
        output_dir=args.output_dir,
        top_n_funds=args.top_funds,
        max_funding_pages=args.max_pages
    )


if __name__ == "__main__":
    main()
