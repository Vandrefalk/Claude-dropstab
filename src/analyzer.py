"""Data analysis module - transforms fund-centric to project-centric view."""
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from .models import FundInvestment, Project, ProjectAnalysis


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse date string like 'Jun 2019' or 'March 2020'."""
    if not date_str:
        return None

    formats = [
        "%b %Y",      # Jun 2019
        "%B %Y",      # June 2019
        "%d %b %Y",   # 15 Jun 2019
        "%d %B %Y",   # 15 June 2019
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue

    return None


def is_within_years(date_str: Optional[str], years: int = 3) -> bool:
    """Check if date is within last N years."""
    if not date_str:
        return True  # Include if no date (conservative approach)

    parsed = parse_date(date_str)
    if not parsed:
        return True

    cutoff = datetime.now().replace(year=datetime.now().year - years)
    return parsed >= cutoff


class ProjectAnalyzer:
    """
    Analyzes investment data with project-centric view.

    Transforms:
        Fund -> [Projects]
    Into:
        Project -> [Funds with investment details]
    """

    def __init__(
        self,
        investments: list[FundInvestment],
        projects: dict[str, Project],
        max_years: int = 3
    ):
        """
        Initialize analyzer.

        Args:
            investments: List of all fund investments
            projects: Dict of project slug -> Project with market cap
            max_years: Max years ago for investment filter
        """
        self.investments = investments
        self.projects = projects
        self.max_years = max_years

    def aggregate_by_project(self) -> dict[str, list[FundInvestment]]:
        """
        Aggregate investments by project.

        Returns:
            Dict of project_slug -> list of investments from different funds
        """
        project_investments: dict[str, list[FundInvestment]] = defaultdict(list)

        for inv in self.investments:
            # Filter by date
            if not is_within_years(inv.date, self.max_years):
                continue

            project_investments[inv.project_slug].append(inv)

        return dict(project_investments)

    def analyze_projects(self) -> list[ProjectAnalysis]:
        """
        Create full analysis for each project.

        Returns:
            List of ProjectAnalysis sorted by investor count
        """
        aggregated = self.aggregate_by_project()
        analyses = []

        for project_slug, investments in aggregated.items():
            # Get project details if available
            project = self.projects.get(project_slug)

            # Calculate totals
            total_invested = sum(inv.amount or 0 for inv in investments)

            market_cap = None
            category = None

            if project:
                market_cap = project.market_cap
                category = project.category

            # Calculate ROI
            roi = None
            if market_cap and total_invested > 0:
                roi = market_cap / total_invested

            # Build investors list
            investors = []
            for inv in investments:
                investors.append({
                    "fund_name": inv.fund_name,
                    "fund_slug": inv.fund_slug,
                    "amount": inv.amount,
                    "date": inv.date,
                    "stage": inv.stage,
                })

            # Sort investors by amount (highest first)
            investors.sort(key=lambda x: x.get("amount") or 0, reverse=True)

            # Get project name from first investment or project
            project_name = investments[0].project_name
            if project:
                project_name = project.name

            analysis = ProjectAnalysis(
                project_slug=project_slug,
                project_name=project_name,
                category=category,
                market_cap=market_cap,
                total_invested=total_invested,
                roi_multiplier=roi,
                investors=investors,
                investor_count=len(investors),
            )
            analyses.append(analysis)

        # Sort by investor count (most popular projects first)
        analyses.sort(key=lambda x: x.investor_count, reverse=True)

        return analyses

    def to_dataframe(self) -> pd.DataFrame:
        """Convert analysis to pandas DataFrame."""
        analyses = self.analyze_projects()

        rows = []
        for a in analyses:
            # Create row for each project
            investor_names = [i["fund_name"] for i in a.investors]
            investor_amounts = [i.get("amount") for i in a.investors]

            rows.append({
                "project": a.project_name,
                "slug": a.project_slug,
                "category": a.category,
                "market_cap": a.market_cap,
                "total_invested": a.total_invested,
                "roi": a.roi_multiplier,
                "investor_count": a.investor_count,
                "investors": ", ".join(investor_names),
                "top_investor": investor_names[0] if investor_names else None,
                "top_investment": investor_amounts[0] if investor_amounts else None,
            })

        return pd.DataFrame(rows)

    def get_project_details_df(self) -> pd.DataFrame:
        """
        Create detailed DataFrame with one row per fund-project pair.

        Useful for detailed analysis of who invested where.
        """
        analyses = self.analyze_projects()

        rows = []
        for a in analyses:
            for inv in a.investors:
                rows.append({
                    "project": a.project_name,
                    "project_slug": a.project_slug,
                    "category": a.category,
                    "market_cap": a.market_cap,
                    "fund": inv["fund_name"],
                    "fund_slug": inv["fund_slug"],
                    "invested_amount": inv.get("amount"),
                    "investment_date": inv.get("date"),
                    "stage": inv.get("stage"),
                    "project_roi": a.roi_multiplier,
                    "total_project_investment": a.total_invested,
                    "investors_in_project": a.investor_count,
                })

        return pd.DataFrame(rows)

    def get_summary_stats(self) -> dict:
        """Get summary statistics."""
        analyses = self.analyze_projects()

        total_projects = len(analyses)
        total_with_mcap = sum(1 for a in analyses if a.market_cap)

        rois = [a.roi_multiplier for a in analyses if a.roi_multiplier]

        # Projects with multiple top investors
        multi_investor = [a for a in analyses if a.investor_count >= 3]

        return {
            "total_projects": total_projects,
            "projects_with_market_cap": total_with_mcap,
            "projects_with_3plus_investors": len(multi_investor),
            "avg_investors_per_project": sum(a.investor_count for a in analyses) / total_projects if total_projects else 0,
            "median_roi": sorted(rois)[len(rois) // 2] if rois else None,
            "avg_roi": sum(rois) / len(rois) if rois else None,
            "max_roi": max(rois) if rois else None,
            "min_roi": min(rois) if rois else None,
        }

    def export_to_csv(self, output_path: str = "analysis.csv"):
        """Export analysis to CSV file."""
        df = self.to_dataframe()
        df.to_csv(output_path, index=False)
        return output_path

    def export_detailed_csv(self, output_path: str = "detailed_analysis.csv"):
        """Export detailed analysis to CSV file."""
        df = self.get_project_details_df()
        df.to_csv(output_path, index=False)
        return output_path
