"""Data collector using DropStab API."""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import asdict

from .api_client import DropStabAPI, APIConfig
from .models import Fund, FundInvestment, Project, ProjectRound

logger = logging.getLogger(__name__)


class DataCollector:
    """Collects and stores data from DropStab API."""

    def __init__(self, api_key: str, output_dir: str = "data/api"):
        self.api = DropStabAPI(api_key)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Storage
        self.investors: list[dict] = []
        self.funding_rounds: list[dict] = []
        self.coins: list[dict] = []

    def _save_json(self, filename: str, data: any):
        """Save data to JSON file."""
        filepath = self.output_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Saved {filepath}")

    def _load_json(self, filename: str) -> any:
        """Load data from JSON file."""
        filepath = self.output_dir / filename
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def load_from_cache(self) -> bool:
        """
        Load previously collected data from cache.

        Returns:
            True if data was loaded, False otherwise
        """
        logger.info(f"Loading cached data from {self.output_dir}...")

        investors = self._load_json("top_investors.json") or self._load_json("investors_raw.json")
        if investors:
            self.investors = investors
            logger.info(f"Loaded {len(self.investors)} investors from cache")

        funding_rounds = self._load_json("funding_rounds_raw.json")
        if funding_rounds:
            self.funding_rounds = funding_rounds
            logger.info(f"Loaded {len(self.funding_rounds)} funding rounds from cache")

        return bool(self.investors or self.funding_rounds)

    def collect_all_investors(self, sort_by: str = "retailRoi") -> list[dict]:
        """
        Collect all investors/funds data.

        Args:
            sort_by: Sort field ('retailRoi', 'privateRoi', 'investmentsCount')

        Returns:
            List of investor dicts
        """
        logger.info("Collecting all investors...")
        self.investors = self.api.get_all_investors(sort_by=sort_by, sort_order="desc")
        self._save_json("investors_raw.json", self.investors)

        logger.info(f"Collected {len(self.investors)} investors")
        return self.investors

    def collect_top_investors(
        self,
        top_n: int = 20,
        by_retail_roi: bool = True,
        by_private_roi: bool = True
    ) -> list[dict]:
        """
        Collect TOP investors by ROI (dual top mode).

        Args:
            top_n: Number of top investors per category
            by_retail_roi: Include top by retail ROI
            by_private_roi: Include top by private ROI

        Returns:
            Combined list of unique top investors
        """
        logger.info(f"Collecting TOP-{top_n} investors (dual mode)...")

        seen_slugs = set()
        combined = []

        if by_retail_roi:
            retail_top = self.api.get_all_investors(sort_by="RETAIL_ROI_PERCENT", sort_order="DESC")[:top_n]
            for inv in retail_top:
                slug = inv.get("investorSlug")
                if slug and slug not in seen_slugs:
                    seen_slugs.add(slug)
                    combined.append(inv)
            logger.info(f"Added {len(retail_top)} from retail ROI top")

        if by_private_roi:
            private_top = self.api.get_all_investors(sort_by="PRIVATE_ROI_PERCENT", sort_order="DESC")[:top_n]
            for inv in private_top:
                slug = inv.get("investorSlug")
                if slug and slug not in seen_slugs:
                    seen_slugs.add(slug)
                    combined.append(inv)
            logger.info(f"Added new investors from private ROI top")

        self.investors = combined
        self._save_json("top_investors.json", combined)

        logger.info(f"Collected {len(combined)} unique top investors")
        return combined

    def collect_investor_details(self, slugs: Optional[list[str]] = None) -> dict[str, dict]:
        """
        Collect detailed info for investors.

        Args:
            slugs: List of investor slugs, or None to use self.investors

        Returns:
            Dict mapping slug to detailed investor data
        """
        if slugs is None:
            slugs = [inv.get("investorSlug") for inv in self.investors if inv.get("investorSlug")]

        logger.info(f"Collecting details for {len(slugs)} investors...")
        details = {}

        for i, slug in enumerate(slugs, 1):
            try:
                logger.info(f"[{i}/{len(slugs)}] Fetching {slug}...")
                details[slug] = self.api.get_investor(slug)
            except Exception as e:
                logger.error(f"Error fetching {slug}: {e}")
                continue

        self._save_json("investor_details.json", details)
        logger.info(f"Collected details for {len(details)} investors")
        return details

    def collect_all_funding_rounds(self) -> list[dict]:
        """
        Collect all funding rounds.

        Returns:
            List of funding round dicts
        """
        logger.info("Collecting all funding rounds...")
        self.funding_rounds = self.api.get_all_funding_rounds()
        self._save_json("funding_rounds_raw.json", self.funding_rounds)

        logger.info(f"Collected {len(self.funding_rounds)} funding rounds")
        return self.funding_rounds

    def collect_funding_rounds_by_investor(self, investor_slugs: list[str]) -> dict[str, list[dict]]:
        """
        Collect funding rounds for specific investors.

        Args:
            investor_slugs: List of investor slugs

        Returns:
            Dict mapping investor slug to their funding rounds
        """
        logger.info(f"Collecting funding rounds for {len(investor_slugs)} investors...")
        result = {}

        for i, slug in enumerate(investor_slugs, 1):
            try:
                logger.info(f"[{i}/{len(investor_slugs)}] Fetching rounds for {slug}...")
                rounds = self.api.get_all_funding_rounds(investor_slug=slug)
                result[slug] = rounds
            except Exception as e:
                logger.error(f"Error fetching rounds for {slug}: {e}")
                continue

        self._save_json("investor_funding_rounds.json", result)
        logger.info(f"Collected rounds for {len(result)} investors")
        return result

    def collect_coin_details(self, slugs: list[str]) -> dict[str, dict]:
        """
        Collect detailed info for coins/projects.

        Args:
            slugs: List of coin slugs

        Returns:
            Dict mapping slug to detailed coin data
        """
        logger.info(f"Collecting details for {len(slugs)} coins...")
        details = {}

        for i, slug in enumerate(slugs, 1):
            try:
                logger.info(f"[{i}/{len(slugs)}] Fetching {slug}...")
                details[slug] = self.api.get_coin_detailed(slug)
            except Exception as e:
                logger.error(f"Error fetching {slug}: {e}")
                continue

        self._save_json("coin_details.json", details)
        logger.info(f"Collected details for {len(details)} coins")
        return details

    def extract_unique_coins(self) -> set[str]:
        """
        Extract unique coin slugs from funding rounds.

        Returns:
            Set of unique coin slugs
        """
        coins = set()
        for round_data in self.funding_rounds:
            coin = round_data.get("coin", {})
            if isinstance(coin, dict) and coin.get("slug"):
                coins.add(coin["slug"])
            elif round_data.get("coinSlug"):
                coins.add(round_data["coinSlug"])
        return coins

    def run_full_collection(
        self,
        top_n: int = 20,
        collect_coin_details: bool = True
    ) -> dict:
        """
        Run full data collection pipeline.

        Args:
            top_n: Number of top investors per category
            collect_coin_details: Whether to fetch detailed coin data

        Returns:
            Summary dict with collection stats
        """
        logger.info("Starting full data collection...")

        # 1. Collect top investors
        self.collect_top_investors(top_n=top_n)

        # 2. Collect investor details
        investor_slugs = [inv.get("investorSlug") for inv in self.investors if inv.get("investorSlug")]
        self.collect_investor_details(investor_slugs)

        # 3. Collect funding rounds for these investors
        self.collect_funding_rounds_by_investor(investor_slugs)

        # 4. Collect all funding rounds
        self.collect_all_funding_rounds()

        # 5. Extract and collect coin details
        if collect_coin_details:
            coin_slugs = list(self.extract_unique_coins())
            logger.info(f"Found {len(coin_slugs)} unique coins in funding rounds")
            self.collect_coin_details(coin_slugs)

        # Save summary
        summary = {
            "collection_date": datetime.now().isoformat(),
            "total_investors": len(self.investors),
            "total_funding_rounds": len(self.funding_rounds),
            "unique_coins": len(self.extract_unique_coins()),
        }
        self._save_json("collection_summary.json", summary)

        logger.info("Full collection completed!")
        logger.info(f"Summary: {summary}")
        return summary


def convert_to_models(collector: DataCollector) -> tuple[list[Fund], list[FundInvestment], list[Project]]:
    """
    Convert raw API data to model objects.

    Returns:
        Tuple of (funds, investments, projects)
    """
    funds = []
    investments = []
    projects_map = {}

    # Convert investors to Fund models
    for inv in collector.investors:
        # Handle binanceListing as object
        binance_listing = inv.get("binanceListing", {})
        binance_pct = binance_listing.get("percent") if isinstance(binance_listing, dict) else None

        fund = Fund(
            rank=inv.get("rank", 0),
            name=inv.get("name", ""),
            slug=inv.get("investorSlug", ""),
            tier=inv.get("tier", ""),
            portfolio_count=inv.get("portfolioCoinsCount", 0),
            investments_count=inv.get("totalInvestments", 0),
            retail_roi=inv.get("retailRoiPercent"),
            private_roi=inv.get("privateRoiPercent"),
            binance_listing_pct=binance_pct,
            latest_round_date=inv.get("lastRoundDate"),
        )
        funds.append(fund)

    # Convert funding rounds to FundInvestment models
    for round_data in collector.funding_rounds:
        project_slug = round_data.get("coinSlug", "")
        project_name = round_data.get("coinSymbol", "")

        # Get investors from this round
        round_investors = round_data.get("investors", []) or []
        for inv in round_investors:
            inv_slug = inv.get("investorSlug", "") if isinstance(inv, dict) else ""
            inv_name = inv.get("name", "") if isinstance(inv, dict) else str(inv)

            investment = FundInvestment(
                fund_slug=inv_slug,
                fund_name=inv_name,
                project_slug=project_slug,
                project_name=project_name,
                amount=round_data.get("fundsRaised"),
                stage=round_data.get("stage", ""),
                date=round_data.get("date"),
                category=round_data.get("category"),
                pre_valuation=round_data.get("preValuation"),
            )
            investments.append(investment)

        # Build project data
        if project_slug and project_slug not in projects_map:
            projects_map[project_slug] = Project(
                name=project_name,
                slug=project_slug,
                category=round_data.get("category"),
                market_cap=None,  # Will be filled from coin details
                price=None,
                total_raised=round_data.get("fundsRaised"),
                rounds=[],
            )

        if project_slug in projects_map:
            proj = projects_map[project_slug]
            proj.rounds.append(ProjectRound(
                stage=round_data.get("stage", ""),
                date=round_data.get("date"),
                price=round_data.get("tokenPrice"),
                amount=round_data.get("fundsRaised"),
                investors=[inv.get("name", "") if isinstance(inv, dict) else str(inv)
                          for inv in round_investors],
            ))

    projects = list(projects_map.values())
    return funds, investments, projects
