"""Main script for DropStab API data collection."""
import argparse
import logging
import json
import os
from datetime import datetime
from pathlib import Path

from .api_client import DropStabAPI
from .api_collector import DataCollector, convert_to_models

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


def test_connection(api_key: str) -> bool:
    """Test API connection."""
    logger.info("Testing API connection...")
    try:
        api = DropStabAPI(api_key)
        result = api.get_investors(page=1, limit=1)
        if "data" in result:
            logger.info("API connection successful!")
            return True
        else:
            logger.error(f"Unexpected response: {result}")
            return False
    except Exception as e:
        logger.error(f"API connection failed: {e}")
        return False


def collect_data(
    api_key: str,
    top_n: int = 20,
    output_dir: str = "data/api",
    full_mode: bool = False
):
    """
    Collect data from DropStab API.

    Args:
        api_key: API key
        top_n: Number of top investors per category
        output_dir: Output directory for raw data
        full_mode: If True, collect ALL investors; if False, only top investors
    """
    collector = DataCollector(api_key, output_dir)

    if full_mode:
        # Collect ALL investors
        logger.info("Running FULL collection mode...")
        collector.collect_all_investors()
    else:
        # Collect top investors by ROI
        logger.info(f"Running TOP-{top_n} collection mode...")
        collector.collect_top_investors(top_n=top_n)

    # Run full collection pipeline
    summary = collector.run_full_collection(
        top_n=top_n,
        collect_coin_details=True
    )

    return collector, summary


def export_data(
    collector: DataCollector,
    export_dir: str = "exports"
):
    """
    Export collected data to CSV and JSON.

    Args:
        collector: DataCollector with fetched data
        export_dir: Export directory
    """
    # Create dated export folder
    date_str = datetime.now().strftime("%Y-%m-%d")
    export_path = Path(export_dir) / f"{date_str}_api"
    export_path.mkdir(parents=True, exist_ok=True)

    # Convert to models
    funds, investments, projects = convert_to_models(collector)

    # Save funds
    funds_data = [
        {
            "rank": f.rank,
            "name": f.name,
            "slug": f.slug,
            "tier": f.tier,
            "portfolio_count": f.portfolio_count,
            "investments_count": f.investments_count,
            "retail_roi": f.retail_roi,
            "private_roi": f.private_roi,
            "binance_listing_pct": f.binance_listing_pct,
        }
        for f in funds
    ]
    with open(export_path / "funds.json", "w") as f:
        json.dump(funds_data, f, indent=2, ensure_ascii=False)

    # Save investments
    inv_data = [
        {
            "fund_slug": inv.fund_slug,
            "fund_name": inv.fund_name,
            "project_slug": inv.project_slug,
            "project_name": inv.project_name,
            "amount": inv.amount,
            "stage": inv.stage,
            "date": inv.date,
            "category": inv.category,
            "pre_valuation": inv.pre_valuation,
        }
        for inv in investments
    ]
    with open(export_path / "investments.json", "w") as f:
        json.dump(inv_data, f, indent=2, ensure_ascii=False)

    # Save projects
    proj_data = [
        {
            "name": p.name,
            "slug": p.slug,
            "category": p.category,
            "market_cap": p.market_cap,
            "price": p.price,
            "total_raised": p.total_raised,
            "rounds_count": len(p.rounds),
        }
        for p in projects
    ]
    with open(export_path / "projects.json", "w") as f:
        json.dump(proj_data, f, indent=2, ensure_ascii=False)

    # Create CSV exports
    import csv

    # Investments CSV
    with open(export_path / "all_investments.csv", "w", newline="", encoding="utf-8") as f:
        if inv_data:
            writer = csv.DictWriter(f, fieldnames=inv_data[0].keys())
            writer.writeheader()
            writer.writerows(inv_data)

    # Projects CSV
    with open(export_path / "projects_summary.csv", "w", newline="", encoding="utf-8") as f:
        if proj_data:
            writer = csv.DictWriter(f, fieldnames=proj_data[0].keys())
            writer.writeheader()
            writer.writerows(proj_data)

    logger.info(f"Exported data to {export_path}")
    logger.info(f"  - {len(funds)} funds")
    logger.info(f"  - {len(investments)} investments")
    logger.info(f"  - {len(projects)} projects")

    return export_path


def main():
    parser = argparse.ArgumentParser(
        description="DropStab API Data Collector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test API connection
  python -m src.api_main test --api-key YOUR_KEY

  # Collect TOP-20 investors (dual mode: retail + private ROI)
  python -m src.api_main collect --api-key YOUR_KEY --top 20

  # Collect ALL investors data
  python -m src.api_main collect --api-key YOUR_KEY --full

  # Collect and export to specific directory
  python -m src.api_main collect --api-key YOUR_KEY --top 30 --output exports/my_data
        """
    )

    parser.add_argument(
        "command",
        choices=["test", "collect"],
        help="Command to run"
    )
    parser.add_argument(
        "--api-key", "-k",
        type=str,
        required=True,
        help="DropStab API key"
    )
    parser.add_argument(
        "--top", "-t",
        type=int,
        default=20,
        help="Number of top investors per category (default: 20)"
    )
    parser.add_argument(
        "--full", "-f",
        action="store_true",
        help="Collect ALL investors, not just top"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="exports",
        help="Export directory (default: exports)"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/api",
        help="Raw data directory (default: data/api)"
    )

    args = parser.parse_args()

    if args.command == "test":
        success = test_connection(args.api_key)
        exit(0 if success else 1)

    elif args.command == "collect":
        # Collect data
        collector, summary = collect_data(
            api_key=args.api_key,
            top_n=args.top,
            output_dir=args.data_dir,
            full_mode=args.full
        )

        # Export
        export_path = export_data(collector, args.output)

        print("\n" + "=" * 50)
        print("Collection completed!")
        print("=" * 50)
        print(f"Investors: {summary['total_investors']}")
        print(f"Funding rounds: {summary['total_funding_rounds']}")
        print(f"Unique coins: {summary['unique_coins']}")
        print(f"\nData exported to: {export_path}")


if __name__ == "__main__":
    main()
