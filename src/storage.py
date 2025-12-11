"""Data storage and caching."""
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import Fund, FundInvestment, Project


class DataStorage:
    """JSON-based data storage for parsed data."""

    def __init__(self, data_dir: str = "data"):
        """Initialize storage with data directory."""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.funds_file = self.data_dir / "funds.json"
        self.investments_file = self.data_dir / "investments.json"
        self.projects_file = self.data_dir / "projects.json"
        self.metadata_file = self.data_dir / "metadata.json"

    def save_funds(self, funds: list[Fund]):
        """Save funds list."""
        data = [asdict(f) for f in funds]
        self._write_json(self.funds_file, data)

    def load_funds(self) -> list[Fund]:
        """Load funds list."""
        data = self._read_json(self.funds_file)
        if not data:
            return []
        return [Fund(**d) for d in data]

    def save_investments(self, investments: list[FundInvestment]):
        """Save investments list."""
        data = [asdict(i) for i in investments]
        self._write_json(self.investments_file, data)

    def load_investments(self) -> list[FundInvestment]:
        """Load investments list."""
        data = self._read_json(self.investments_file)
        if not data:
            return []
        return [FundInvestment(**d) for d in data]

    def append_investments(self, investments: list[FundInvestment]):
        """Append investments to existing data, deduplicating by (fund_slug, project_slug)."""
        existing = self.load_investments()

        # Create set of existing (fund_slug, project_slug) pairs
        existing_pairs = {(inv.fund_slug, inv.project_slug) for inv in existing}

        # Only add investments that don't already exist
        new_investments = [
            inv for inv in investments
            if (inv.fund_slug, inv.project_slug) not in existing_pairs
        ]

        existing.extend(new_investments)
        self.save_investments(existing)

    def save_projects(self, projects: dict[str, Project]):
        """Save projects dict (slug -> Project)."""
        data = {slug: asdict(p) for slug, p in projects.items()}
        self._write_json(self.projects_file, data)

    def load_projects(self) -> dict[str, Project]:
        """Load projects dict."""
        data = self._read_json(self.projects_file)
        if not data:
            return {}

        projects = {}
        for slug, d in data.items():
            # Handle nested dataclasses
            if "rounds" in d:
                from .models import ProjectRound
                d["rounds"] = [ProjectRound(**r) for r in d["rounds"]]
            if "fund_investments" in d:
                d["fund_investments"] = {
                    k: FundInvestment(**v)
                    for k, v in d["fund_investments"].items()
                }
            projects[slug] = Project(**d)

        return projects

    def save_metadata(self, key: str, value):
        """Save metadata value."""
        data = self._read_json(self.metadata_file) or {}
        data[key] = value
        data["last_updated"] = datetime.now().isoformat()
        self._write_json(self.metadata_file, data)

    def get_metadata(self, key: str, default=None):
        """Get metadata value."""
        data = self._read_json(self.metadata_file) or {}
        return data.get(key, default)

    def get_parsed_fund_slugs(self) -> set[str]:
        """Get set of already parsed fund slugs."""
        return set(self.get_metadata("parsed_funds", []))

    def mark_fund_parsed(self, fund_slug: str):
        """Mark a fund as parsed."""
        parsed = self.get_parsed_fund_slugs()
        parsed.add(fund_slug)
        self.save_metadata("parsed_funds", list(parsed))

    def _write_json(self, path: Path, data):
        """Write data to JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _read_json(self, path: Path) -> Optional[dict | list]:
        """Read data from JSON file."""
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def clear(self):
        """Clear all stored data."""
        for f in [self.funds_file, self.investments_file, self.projects_file, self.metadata_file]:
            if f.exists():
                f.unlink()
