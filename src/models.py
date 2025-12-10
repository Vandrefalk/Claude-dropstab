"""Data models for DropStab parser."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Fund:
    """Investment fund data."""
    rank: int
    name: str
    slug: str
    tier: str
    portfolio_count: int
    investments_count: int
    retail_roi: Optional[float] = None
    private_roi: Optional[float] = None
    binance_listing_pct: Optional[float] = None
    latest_round_date: Optional[str] = None


@dataclass
class FundInvestment:
    """Investment made by a fund into a project."""
    fund_slug: str
    fund_name: str
    project_slug: str
    project_name: str
    amount: Optional[float]  # in USD
    stage: str  # Seed, Series A, etc.
    date: Optional[str]
    category: Optional[str] = None
    pre_valuation: Optional[float] = None


@dataclass
class ProjectRound:
    """Single fundraising round for a project."""
    stage: str
    date: Optional[str]
    price: Optional[float]
    amount: Optional[float]
    investors: list[str] = field(default_factory=list)


@dataclass
class Project:
    """Project with all its fundraising data."""
    name: str
    slug: str
    category: Optional[str]
    market_cap: Optional[float]
    price: Optional[float]
    total_raised: Optional[float]
    rounds: list[ProjectRound] = field(default_factory=list)

    # Aggregated from fund investments
    fund_investments: dict[str, FundInvestment] = field(default_factory=dict)
    # key = fund_slug, value = investment details


@dataclass
class ProjectAnalysis:
    """Analyzed project with ROI calculations."""
    project_slug: str
    project_name: str
    category: Optional[str]
    market_cap: Optional[float]
    total_invested: float
    roi_multiplier: Optional[float]  # market_cap / total_invested
    investors: list[dict]  # [{fund_name, amount, date, stage}]
    investor_count: int
