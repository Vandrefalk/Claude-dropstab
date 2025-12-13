"""DropStab API Client for fetching fund and investment data."""
import time
import logging
from typing import Optional, Any
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)


@dataclass
class APIConfig:
    """API configuration."""
    base_url: str = "https://public-api.dropstab.com/api/v1"
    api_key: str = ""
    request_delay: float = 0.5  # delay between requests in seconds
    timeout: int = 30


class DropStabAPIError(Exception):
    """Custom exception for API errors."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"API Error {status_code}: {message}")


class DropStabAPI:
    """Client for DropStab REST API."""

    def __init__(self, api_key: str, config: Optional[APIConfig] = None):
        self.config = config or APIConfig()
        self.config.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
        self._last_request_time = 0

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.config.request_delay:
            time.sleep(self.config.request_delay - elapsed)
        self._last_request_time = time.time()

    def _request(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Make a GET request to the API."""
        self._rate_limit()

        url = f"{self.config.base_url}/{endpoint.lstrip('/')}"
        logger.debug(f"GET {url} params={params}")

        try:
            response = self.session.get(url, params=params, timeout=self.config.timeout)

            if response.status_code == 429:
                # Rate limited - wait and retry
                retry_after = int(response.headers.get("Retry-After", 60))
                logger.warning(f"Rate limited, waiting {retry_after}s")
                time.sleep(retry_after)
                return self._request(endpoint, params)

            if response.status_code != 200:
                raise DropStabAPIError(response.status_code, response.text)

            return response.json()

        except requests.exceptions.Timeout:
            logger.error(f"Request timeout: {url}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            raise

    # === Investors/Funds Endpoints ===

    def get_investors(
        self,
        page: int = 1,
        limit: int = 100,
        sort_by: Optional[str] = None,
        sort_order: str = "desc"
    ) -> dict:
        """
        Get list of investors/funds.

        Args:
            page: Page number (1-indexed)
            limit: Items per page (max 100)
            sort_by: Field to sort by (e.g., 'retailRoi', 'privateRoi', 'investmentsCount')
            sort_order: 'asc' or 'desc'

        Returns:
            dict with 'data' list and 'pagination' info
        """
        params = {
            "page": page,
            "limit": limit,
        }
        if sort_by:
            params["sortBy"] = sort_by
            params["sortOrder"] = sort_order

        return self._request("/investors", params)

    def get_investor(self, slug: str) -> dict:
        """
        Get detailed info about a specific investor/fund.

        Args:
            slug: Investor slug (e.g., 'a16z', 'binance-labs')

        Returns:
            dict with investor details including portfolio
        """
        return self._request(f"/investors/{slug}")

    def get_all_investors(
        self,
        sort_by: Optional[str] = None,
        sort_order: str = "desc",
        max_pages: int = 50
    ) -> list[dict]:
        """
        Fetch all investors with pagination.

        Args:
            sort_by: Field to sort by
            sort_order: 'asc' or 'desc'
            max_pages: Maximum pages to fetch

        Returns:
            List of all investor dicts
        """
        all_investors = []
        page = 1

        while page <= max_pages:
            logger.info(f"Fetching investors page {page}...")
            result = self.get_investors(page=page, limit=100, sort_by=sort_by, sort_order=sort_order)

            data = result.get("data", [])
            if not data:
                break

            all_investors.extend(data)

            # Check if more pages
            pagination = result.get("pagination", {})
            total_pages = pagination.get("totalPages", 1)
            if page >= total_pages:
                break

            page += 1

        logger.info(f"Fetched {len(all_investors)} investors total")
        return all_investors

    # === Funding Rounds Endpoints ===

    def get_funding_rounds(
        self,
        page: int = 1,
        limit: int = 100,
        coin_slug: Optional[str] = None,
        investor_slug: Optional[str] = None
    ) -> dict:
        """
        Get funding rounds.

        Args:
            page: Page number
            limit: Items per page
            coin_slug: Filter by coin/project slug
            investor_slug: Filter by investor slug

        Returns:
            dict with 'data' list and pagination
        """
        params = {"page": page, "limit": limit}
        if coin_slug:
            params["coinSlug"] = coin_slug
        if investor_slug:
            params["investorSlug"] = investor_slug

        return self._request("/fundingRounds", params)

    def get_funding_round(self, round_id: str) -> dict:
        """Get specific funding round by ID."""
        return self._request(f"/fundingRounds/{round_id}")

    def get_coin_funding_rounds(self, coin_slug: str) -> dict:
        """Get all funding rounds for a specific coin/project."""
        return self._request(f"/fundingRounds/coin/{coin_slug}")

    def get_all_funding_rounds(
        self,
        investor_slug: Optional[str] = None,
        max_pages: int = 100
    ) -> list[dict]:
        """
        Fetch all funding rounds with pagination.

        Args:
            investor_slug: Optional filter by investor
            max_pages: Maximum pages to fetch

        Returns:
            List of all funding round dicts
        """
        all_rounds = []
        page = 1

        while page <= max_pages:
            logger.info(f"Fetching funding rounds page {page}...")
            result = self.get_funding_rounds(
                page=page,
                limit=100,
                investor_slug=investor_slug
            )

            data = result.get("data", [])
            if not data:
                break

            all_rounds.extend(data)

            pagination = result.get("pagination", {})
            total_pages = pagination.get("totalPages", 1)
            if page >= total_pages:
                break

            page += 1

        logger.info(f"Fetched {len(all_rounds)} funding rounds total")
        return all_rounds

    # === Coins/Projects Endpoints ===

    def get_coins(
        self,
        page: int = 1,
        limit: int = 100,
        sort_by: Optional[str] = None
    ) -> dict:
        """
        Get list of coins/tokens.

        Args:
            page: Page number
            limit: Items per page
            sort_by: Field to sort by

        Returns:
            dict with 'data' list and pagination
        """
        params = {"page": page, "limit": limit}
        if sort_by:
            params["sortBy"] = sort_by

        return self._request("/coins", params)

    def get_coin_detailed(self, slug: str) -> dict:
        """
        Get detailed info about a coin/project.

        Args:
            slug: Coin slug (e.g., 'ethereum', 'solana')

        Returns:
            dict with detailed coin info including fundraising
        """
        return self._request(f"/coins/detailed/{slug}")

    def get_supported_coins(self) -> list[dict]:
        """Get list of supported coins."""
        return self._request("/coins/supported")

    # === Crypto Activities Endpoints ===

    def get_crypto_activities(
        self,
        page: int = 1,
        limit: int = 100,
        coin_slug: Optional[str] = None
    ) -> dict:
        """
        Get crypto activities/events.

        Args:
            page: Page number
            limit: Items per page
            coin_slug: Filter by coin slug

        Returns:
            dict with activities data
        """
        params = {"page": page, "limit": limit}
        if coin_slug:
            params["coinSlug"] = coin_slug

        return self._request("/cryptoActivities", params)

    # === Token Unlocks Endpoints ===

    def get_token_unlocks(self, coin_slug: Optional[str] = None) -> dict:
        """
        Get token unlock schedules.

        Args:
            coin_slug: Optional specific coin

        Returns:
            dict with unlock data
        """
        if coin_slug:
            return self._request(f"/tokenUnlocks/{coin_slug}")
        return self._request("/tokenUnlocks")

    # === Price History Endpoints ===

    def get_price_history(
        self,
        slug: str,
        timeframe: str = "1d",
        from_timestamp: Optional[int] = None,
        to_timestamp: Optional[int] = None
    ) -> dict:
        """
        Get price history for a coin.

        Args:
            slug: Coin slug
            timeframe: '1d', '7d', '30d', '90d', '365d', 'all'
            from_timestamp: Unix timestamp for start
            to_timestamp: Unix timestamp for end

        Returns:
            dict with price chart data
        """
        params = {"timeframe": timeframe}
        if from_timestamp:
            params["from"] = from_timestamp
        if to_timestamp:
            params["to"] = to_timestamp

        return self._request(f"/coins/history/chart-by-timeframe/{slug}", params)
