"""DropStab website parser."""
import json
import re
import time
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .models import Fund, FundInvestment, Project, ProjectRound


class DropStabParser:
    """Parser for dropstab.com investor data."""

    BASE_URL = "https://dropstab.com"

    def __init__(self, delay: float = 1.5):
        """
        Initialize parser.

        Args:
            delay: Delay between requests in seconds (rate limiting)
        """
        self.delay = delay
        self.client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
            timeout=30.0,
            follow_redirects=True,
        )
        self._last_request_time = 0

    def _rate_limit(self):
        """Apply rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request_time = time.time()

    def _get(self, url: str, retries: int = 3) -> Optional[str]:
        """
        Make GET request with retries.

        Args:
            url: URL to fetch
            retries: Number of retry attempts

        Returns:
            HTML content or None if failed
        """
        self._rate_limit()

        for attempt in range(retries):
            try:
                response = self.client.get(url)
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as e:
                print(f"Request failed (attempt {attempt + 1}/{retries}): {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
        return None

    def _parse_number(self, text: str) -> Optional[float]:
        """Parse number from text like '$77.23B', '359.70M', etc."""
        if not text:
            return None

        text = text.strip().replace(",", "").replace("$", "")

        multipliers = {
            "T": 1_000_000_000_000,
            "B": 1_000_000_000,
            "M": 1_000_000,
            "K": 1_000,
        }

        for suffix, mult in multipliers.items():
            if text.upper().endswith(suffix):
                try:
                    return float(text[:-1]) * mult
                except ValueError:
                    return None

        try:
            return float(text)
        except ValueError:
            return None

    def _parse_percentage(self, text: str) -> Optional[float]:
        """Parse percentage from text like '45%', '12.5%'."""
        if not text:
            return None
        match = re.search(r"([\d.]+)%", text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    def _parse_roi(self, text: str) -> Optional[float]:
        """Parse ROI value like '12.5x', '-5.2x', '100x'."""
        if not text:
            return None
        # Remove any whitespace and handle negative values
        text = text.strip()
        match = re.search(r"(-?[\d.]+)x", text, re.I)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    def get_all_investors(self, max_pages: int = 10) -> list[Fund]:
        """
        Get all investors from multiple pages.

        Args:
            max_pages: Maximum number of pages to fetch (20 per page)

        Returns:
            List of Fund objects with ROI data
        """
        all_funds = []

        for page in range(1, max_pages + 1):
            url = f"{self.BASE_URL}/investors"
            if page > 1:
                url = f"{url}?page={page}"

            html = self._get(url)
            if not html:
                break

            soup = BeautifulSoup(html, "lxml")
            rows = soup.select("table tbody tr")

            if not rows:
                break

            page_funds = []

            for row in rows:
                try:
                    cells = row.find_all("td")
                    if len(cells) < 5:
                        continue

                    # Extract fund name and slug from link
                    link = row.select_one("a[href*='/investors/']")
                    if not link:
                        continue

                    href = link.get("href", "")
                    slug = href.replace("/investors/", "").strip("/")

                    # Skip if we already have this fund (deduplication)
                    if any(f.slug == slug for f in all_funds) or any(f.slug == slug for f in page_funds):
                        continue

                    # Get fund name from slug (most reliable)
                    # Slug format: "jump-trading", "a16z-andreessen-horowitz"
                    name = slug.replace("-", " ").title()

                    # Special cases for known abbreviations
                    name_lower = name.lower()
                    if "a16z" in name_lower:
                        name = "Andreessen Horowitz (a16z)"
                    elif name_lower == "pantera capital":
                        name = "Pantera Capital"

                    # Extract tier from second cell typically
                    tier = ""
                    if len(cells) > 2:
                        tier_cell = cells[2]
                        tier_text = tier_cell.get_text(strip=True)
                        if "Tier" in tier_text or tier_text in ["Exchange", "Angel Investor", "DAO"]:
                            tier = tier_text

                    # Parse all cell values to find ROI
                    retail_roi = None
                    private_roi = None
                    portfolio_count = 0
                    investments_count = 0
                    binance_pct = None

                    row_text = row.get_text()

                    # Look for ROI values in cells
                    for cell in cells:
                        cell_text = cell.get_text(strip=True)

                        # Check for ROI (contains 'x')
                        if "x" in cell_text.lower() and re.search(r"[\d.]+x", cell_text, re.I):
                            roi_val = self._parse_roi(cell_text)
                            if roi_val is not None:
                                # First ROI is usually Retail, second is Private
                                if retail_roi is None:
                                    retail_roi = roi_val
                                elif private_roi is None:
                                    private_roi = roi_val

                        # Check for percentage (Binance listing)
                        if "%" in cell_text:
                            pct = self._parse_percentage(cell_text)
                            if pct is not None and binance_pct is None:
                                binance_pct = pct

                        # Check for pure numbers (counts)
                        if cell_text.isdigit():
                            num = int(cell_text)
                            if portfolio_count == 0:
                                portfolio_count = num
                            elif investments_count == 0:
                                investments_count = num

                    fund = Fund(
                        rank=len(all_funds) + len(page_funds) + 1,
                        name=name,
                        slug=slug,
                        tier=tier,
                        portfolio_count=portfolio_count,
                        investments_count=investments_count,
                        retail_roi=retail_roi,
                        private_roi=private_roi,
                        binance_listing_pct=binance_pct,
                    )
                    page_funds.append(fund)

                except Exception as e:
                    print(f"Error parsing fund row: {e}")
                    continue

            if not page_funds:
                break

            all_funds.extend(page_funds)
            print(f"Parsed page {page}: {len(page_funds)} funds")

        return all_funds

    def get_top_investors(
        self,
        limit: int = 20,
        sort_by: str = "retail_roi",
        min_tier: str = None,
        fetch_pages: int = 5
    ) -> list[Fund]:
        """
        Get top investors sorted by ROI.

        Args:
            limit: Number of top investors to return
            sort_by: 'retail_roi' or 'private_roi'
            min_tier: Minimum tier filter (e.g., 'Tier 1')
            fetch_pages: Number of pages to fetch for sorting

        Returns:
            List of Fund objects sorted by chosen ROI metric
        """
        # Fetch enough funds to sort
        all_funds = self.get_all_investors(max_pages=fetch_pages)

        # Filter by tier if specified
        if min_tier:
            all_funds = [f for f in all_funds if min_tier.lower() in f.tier.lower()]

        # Sort by chosen metric
        if sort_by == "private_roi":
            # Sort by private ROI (descending), None values last
            all_funds.sort(
                key=lambda f: (f.private_roi is not None, f.private_roi or 0),
                reverse=True
            )
        else:  # retail_roi (default)
            all_funds.sort(
                key=lambda f: (f.retail_roi is not None, f.retail_roi or 0),
                reverse=True
            )

        # Update ranks after sorting
        for i, fund in enumerate(all_funds[:limit]):
            fund.rank = i + 1

        return all_funds[:limit]

    def _clean_project_name(self, name: str) -> str:
        """Remove ticker prefix from project name (e.g., 'SOLSolana' -> 'Solana')."""
        if not name:
            return name

        # Pattern: uppercase ticker followed by capitalized name
        # Examples: SOLSolana, LDOLido DAO, WWormhole, ANCAnchor Protocol
        match = re.match(r'^([A-Z]{1,5})([A-Z][a-z].*)', name)
        if match:
            ticker = match.group(1)
            rest = match.group(2)
            # Only clean if ticker is different from the rest
            if not rest.upper().startswith(ticker):
                return rest

        return name

    def get_fund_investments(
        self,
        fund_slug: str,
        fund_name: str,
        max_pages: int = 15
    ) -> list[FundInvestment]:
        """
        Get all investments for a fund.

        Args:
            fund_slug: Fund URL slug
            fund_name: Fund display name
            max_pages: Maximum number of pages to fetch

        Returns:
            List of FundInvestment objects
        """
        investments = []
        seen_slugs = set()  # Track seen project slugs to avoid duplicates
        page = 1

        while page <= max_pages:
            url = f"{self.BASE_URL}/investors/{fund_slug}"
            if page > 1:
                url = f"{url}?page={page}"

            html = self._get(url)
            if not html:
                break

            soup = BeautifulSoup(html, "lxml")
            rows = soup.select("table tbody tr")

            if not rows:
                break

            page_investments = []
            new_projects_on_page = 0

            for row in rows:
                try:
                    # Find project link
                    link = row.select_one("a[href*='/coins/']")
                    if not link:
                        continue

                    href = link.get("href", "")
                    # Extract slug from /coins/xxx or /coins/xxx/fundraising
                    slug_match = re.search(r"/coins/([^/]+)", href)
                    if not slug_match:
                        continue

                    project_slug = slug_match.group(1)

                    # Skip if already seen (deduplication)
                    if project_slug in seen_slugs:
                        continue
                    seen_slugs.add(project_slug)
                    new_projects_on_page += 1

                    project_name = self._clean_project_name(link.get_text(strip=True))

                    cells = row.find_all("td")

                    # Parse investment data from cells
                    amount = None
                    stage = ""
                    date = None
                    category = None
                    pre_valuation = None

                    for cell in cells:
                        text = cell.get_text(strip=True)

                        # Check for amount (contains $ and M/K/B)
                        if "$" in text and any(s in text.upper() for s in ["M", "K", "B"]):
                            if amount is None:  # First amount is usually fundraise
                                amount = self._parse_number(text)
                            elif pre_valuation is None:  # Second might be pre-valuation
                                pre_valuation = self._parse_number(text)

                        # Check for stage
                        if any(s in text for s in ["Seed", "Series", "Round", "Private", "Strategic", "Pre-"]):
                            stage = text

                        # Check for date (format: Mon YYYY or DD Mon YYYY)
                        date_match = re.search(r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})", text)
                        if date_match:
                            date = date_match.group(1)

                    investment = FundInvestment(
                        fund_slug=fund_slug,
                        fund_name=fund_name,
                        project_slug=project_slug,
                        project_name=project_name,
                        amount=amount,
                        stage=stage,
                        date=date,
                        category=category,
                        pre_valuation=pre_valuation,
                    )
                    page_investments.append(investment)

                except Exception as e:
                    print(f"Error parsing investment row: {e}")
                    continue

            if not page_investments:
                break

            investments.extend(page_investments)

            # If no new projects on this page, we've likely hit duplicates - stop
            if new_projects_on_page == 0:
                break

            # Check if there are more pages
            if f"page={page + 1}" not in html:
                break

            page += 1

        return investments

    def get_project_details(self, project_slug: str) -> Optional[Project]:
        """
        Get project details including market cap and fundraising rounds.

        Args:
            project_slug: Project URL slug

        Returns:
            Project object or None if failed
        """
        url = f"{self.BASE_URL}/coins/{project_slug}/fundraising"
        html = self._get(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "lxml")

        # Get project name
        name = project_slug.replace("-", " ").title()
        title = soup.select_one("h1")
        if title:
            name = title.get_text(strip=True)

        # Get market cap
        market_cap = None
        price = None

        # Look for market cap text
        page_text = soup.get_text()

        # Try to find market cap - format: "Market Cap $76.76 B" (with space before suffix)
        mcap_match = re.search(
            r"Market\s*Cap\s*\$?([\d.]+)\s*([TBMK])",
            page_text,
            re.I
        )
        if mcap_match:
            number = mcap_match.group(1)
            suffix = mcap_match.group(2).upper()
            market_cap = self._parse_number(f"{number}{suffix}")

        # Try to find price - look for token price pattern
        price_match = re.search(r"\$(\d+(?:,\d{3})*(?:\.\d+)?)", page_text)
        if price_match:
            try:
                price = float(price_match.group(1).replace(",", ""))
            except ValueError:
                pass

        # Get total raised - format may have space before suffix
        total_raised = None
        raised_match = re.search(
            r"(?:Total\s*(?:Raised|Funding))[:\s]*\$?([\d.]+)\s*([TBMK])?",
            page_text,
            re.I
        )
        if raised_match:
            number = raised_match.group(1)
            suffix = raised_match.group(2) or ""
            total_raised = self._parse_number(f"{number}{suffix}")

        # Parse fundraising rounds
        rounds = []
        round_rows = soup.select("table tbody tr")

        for row in round_rows:
            try:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue

                text = row.get_text()

                # Extract round info
                stage = ""
                date = None
                round_price = None
                amount = None

                for cell in cells:
                    cell_text = cell.get_text(strip=True)

                    if any(s in cell_text for s in ["Seed", "Series", "Round", "Private", "Strategic", "Pre-", "Sale", "ICO", "IDO"]):
                        stage = cell_text

                    date_match = re.search(r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})", cell_text)
                    if date_match:
                        date = date_match.group(1)

                    if "$" in cell_text:
                        parsed = self._parse_number(cell_text)
                        if parsed:
                            if parsed < 100:  # Likely a price
                                round_price = parsed
                            else:  # Likely an amount
                                amount = parsed

                if stage or amount:
                    rounds.append(ProjectRound(
                        stage=stage,
                        date=date,
                        price=round_price,
                        amount=amount,
                    ))

            except Exception as e:
                print(f"Error parsing round row: {e}")
                continue

        # Get category
        category = None
        cat_elem = soup.select_one("[class*='category'], [class*='tag']")
        if cat_elem:
            category = cat_elem.get_text(strip=True)

        return Project(
            name=name,
            slug=project_slug,
            category=category,
            market_cap=market_cap,
            price=price,
            total_raised=total_raised,
            rounds=rounds,
        )

    def close(self):
        """Close HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
