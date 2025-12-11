#!/usr/bin/env python3
"""
DropStab Investor Analytics

Parses investment data from dropstab.com and creates project-centric analysis.

Usage:
    python -m src.main parse      # Parse data from website
    python -m src.main analyze    # Analyze parsed data
    python -m src.main all        # Parse and analyze
"""
import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from rich.panel import Panel

from .parser import DropStabParser
from .storage import DataStorage
from .analyzer import ProjectAnalyzer


console = Console()


def format_number(n: float | None) -> str:
    """Format large numbers with B/M/K suffix."""
    if n is None:
        return "N/A"
    if n >= 1_000_000_000:
        return f"${n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"${n / 1_000:.2f}K"
    return f"${n:.2f}"


def format_roi(roi: float | None) -> str:
    """Format ROI multiplier."""
    if roi is None:
        return "N/A"
    if roi >= 1000:
        return f"[bold green]{roi:.0f}x[/]"
    if roi >= 100:
        return f"[green]{roi:.1f}x[/]"
    if roi >= 10:
        return f"[yellow]{roi:.1f}x[/]"
    if roi >= 1:
        return f"{roi:.2f}x"
    return f"[red]{roi:.2f}x[/]"


def parse_data(
    top_n: int = 20,
    max_years: int = 3,
    data_dir: str = "data",
    sort_by: str = "retail_roi",
    fetch_pages: int = 5
):
    """Parse data from DropStab website."""
    storage = DataStorage(data_dir)

    if sort_by == "dual":
        sort_label = "Retail ROI + Private ROI (combined)"
    elif sort_by == "private_roi":
        sort_label = "Private ROI"
    else:
        sort_label = "Retail ROI"

    console.print(Panel.fit(
        f"[bold blue]DropStab Parser[/]\n"
        f"Parsing TOP-{top_n} investors by {sort_label}\n"
        f"Filter: investments within last {max_years} years",
        title="Starting"
    ))

    with DropStabParser(delay=1.5) as parser:
        # Step 1: Get top investors
        console.print(f"\n[bold]Step 1:[/] Fetching top investors by {sort_label}...")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(f"Fetching {fetch_pages} pages of investors...", total=None)

            if sort_by == "dual":
                funds = parser.get_dual_top_investors(
                    limit=top_n,
                    fetch_pages=fetch_pages
                )
            else:
                funds = parser.get_top_investors(
                    limit=top_n,
                    sort_by=sort_by,
                    fetch_pages=fetch_pages
                )
            progress.update(task, completed=True)

        if not funds:
            console.print("[red]Failed to fetch investors list[/]")
            return

        # Display top funds with ROI
        console.print(f"\n[green]TOP-{len(funds)} investors by {sort_label}:[/]")
        funds_table = Table(title=f"Selected Funds (sorted by {sort_label})")
        funds_table.add_column("#", justify="right", style="dim")
        funds_table.add_column("Fund", style="cyan")
        funds_table.add_column("Tier")
        funds_table.add_column("Retail ROI", justify="right")
        funds_table.add_column("Private ROI", justify="right")

        for f in funds:
            funds_table.add_row(
                str(f.rank),
                f.name,
                f.tier or "-",
                f"{f.retail_roi:.1f}x" if f.retail_roi else "N/A",
                f"{f.private_roi:.1f}x" if f.private_roi else "N/A",
            )

        console.print(funds_table)
        storage.save_funds(funds)

        # Step 2: Get investments for each fund
        console.print(f"\n[bold]Step 2:[/] Fetching investments for each fund...")

        all_investments = []
        parsed_slugs = storage.get_parsed_fund_slugs()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task = progress.add_task("Parsing funds...", total=len(funds))

            for fund in funds:
                if fund.slug in parsed_slugs:
                    console.print(f"  [dim]Skipping {fund.name} (cached)[/]")
                    progress.advance(task)
                    continue

                progress.update(task, description=f"Parsing {fund.name}...")

                investments = parser.get_fund_investments(
                    fund_slug=fund.slug,
                    fund_name=fund.name
                )

                all_investments.extend(investments)
                storage.append_investments(investments)
                storage.mark_fund_parsed(fund.slug)

                console.print(f"  [green]{fund.name}:[/] {len(investments)} investments")
                progress.advance(task)

        # Load all investments (including cached)
        all_investments = storage.load_investments()
        console.print(f"\n[bold green]Total investments collected: {len(all_investments)}[/]")

        # Step 3: Get unique projects and fetch their details
        unique_projects = set(inv.project_slug for inv in all_investments)
        console.print(f"\n[bold]Step 3:[/] Fetching details for {len(unique_projects)} unique projects...")

        projects = storage.load_projects()
        projects_to_fetch = [p for p in unique_projects if p not in projects]

        if projects_to_fetch:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                console=console
            ) as progress:
                task = progress.add_task("Fetching project details...", total=len(projects_to_fetch))

                for project_slug in projects_to_fetch:
                    progress.update(task, description=f"Fetching {project_slug}...")

                    project = parser.get_project_details(project_slug)
                    if project:
                        projects[project_slug] = project

                    progress.advance(task)

            storage.save_projects(projects)

        console.print(f"[bold green]Project details collected: {len(projects)}[/]")

    console.print(Panel.fit("[bold green]Parsing complete![/]", title="Done"))


def analyze_data(max_years: int = 3, data_dir: str = "data", output_dir: str = "output"):
    """Analyze parsed data and generate reports."""
    storage = DataStorage(data_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    console.print(Panel.fit(
        f"[bold blue]DropStab Analyzer[/]\n"
        f"Filter: investments within last {max_years} years",
        title="Starting Analysis"
    ))

    # Load data
    investments = storage.load_investments()
    projects = storage.load_projects()

    if not investments:
        console.print("[red]No investment data found. Run 'parse' first.[/]")
        return

    console.print(f"Loaded {len(investments)} investments, {len(projects)} projects")

    # Create analyzer
    analyzer = ProjectAnalyzer(investments, projects, max_years=max_years)

    # Get analyses
    analyses = analyzer.analyze_projects()
    stats = analyzer.get_summary_stats()

    # Display summary
    console.print("\n[bold]Summary Statistics:[/]")
    summary_table = Table(show_header=False, box=None)
    summary_table.add_row("Total projects analyzed:", str(stats["total_projects"]))
    summary_table.add_row("Projects with market cap:", str(stats["projects_with_market_cap"]))
    summary_table.add_row("Projects with 3+ investors:", str(stats["projects_with_3plus_investors"]))
    summary_table.add_row("Avg investors per project:", f"{stats['avg_investors_per_project']:.1f}")
    if stats["avg_roi"]:
        summary_table.add_row("Average ROI:", f"{stats['avg_roi']:.1f}x")
        summary_table.add_row("Max ROI:", f"{stats['max_roi']:.1f}x")
    console.print(summary_table)

    # Display top projects by investor count
    console.print("\n[bold]Top Projects by Investor Count:[/]")
    table = Table(title="Most Popular Projects Among Top Funds")
    table.add_column("Project", style="cyan")
    table.add_column("Category")
    table.add_column("Market Cap", justify="right")
    table.add_column("Total Invested", justify="right")
    table.add_column("ROI", justify="right")
    table.add_column("Investors", justify="center")
    table.add_column("Top Investors")

    for a in analyses[:20]:
        top_investors = ", ".join([i["fund_name"] for i in a.investors[:3]])
        table.add_row(
            a.project_name,
            a.category or "-",
            format_number(a.market_cap),
            format_number(a.total_invested),
            format_roi(a.roi_multiplier),
            str(a.investor_count),
            top_investors
        )

    console.print(table)

    # Display top projects by ROI
    analyses_with_roi = [a for a in analyses if a.roi_multiplier and a.roi_multiplier > 0]
    analyses_with_roi.sort(key=lambda x: x.roi_multiplier or 0, reverse=True)

    if analyses_with_roi:
        console.print("\n[bold]Top Projects by ROI:[/]")
        roi_table = Table(title="Best Performing Investments")
        roi_table.add_column("Project", style="cyan")
        roi_table.add_column("Market Cap", justify="right")
        roi_table.add_column("Total Invested", justify="right")
        roi_table.add_column("ROI", justify="right")
        roi_table.add_column("Investors")

        for a in analyses_with_roi[:15]:
            investors = ", ".join([i["fund_name"] for i in a.investors[:3]])
            roi_table.add_row(
                a.project_name,
                format_number(a.market_cap),
                format_number(a.total_invested),
                format_roi(a.roi_multiplier),
                investors
            )

        console.print(roi_table)

    # Export to CSV
    csv_path = output_path / "projects_analysis.csv"
    detailed_csv_path = output_path / "detailed_investments.csv"

    analyzer.export_to_csv(str(csv_path))
    analyzer.export_detailed_csv(str(detailed_csv_path))

    console.print(f"\n[bold green]Reports exported:[/]")
    console.print(f"  - {csv_path}")
    console.print(f"  - {detailed_csv_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="DropStab Investor Analytics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m src.main parse --top 20
    python -m src.main analyze --years 2
    python -m src.main all --top 20 --years 3
        """
    )

    parser.add_argument(
        "command",
        choices=["parse", "analyze", "all"],
        help="Command to run"
    )
    parser.add_argument(
        "--top", "-t",
        type=int,
        default=20,
        help="Number of top investors to parse (default: 20)"
    )
    parser.add_argument(
        "--years", "-y",
        type=int,
        default=3,
        help="Max years ago for investment filter (default: 3)"
    )
    parser.add_argument(
        "--sort-by", "-s",
        type=str,
        choices=["retail_roi", "private_roi", "dual"],
        default="retail_roi",
        help="Sort investors by: retail_roi, private_roi, or dual (both combined) (default: retail_roi)"
    )
    parser.add_argument(
        "--fetch-pages", "-p",
        type=int,
        default=5,
        help="Number of investor pages to fetch for sorting (default: 5, ~100 funds)"
    )
    parser.add_argument(
        "--data-dir", "-d",
        type=str,
        default="data",
        help="Directory for cached data (default: data)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="output",
        help="Directory for output files (default: output)"
    )

    args = parser.parse_args()

    try:
        if args.command == "parse":
            parse_data(
                top_n=args.top,
                max_years=args.years,
                data_dir=args.data_dir,
                sort_by=args.sort_by,
                fetch_pages=args.fetch_pages
            )
        elif args.command == "analyze":
            analyze_data(
                max_years=args.years,
                data_dir=args.data_dir,
                output_dir=args.output_dir
            )
        elif args.command == "all":
            parse_data(
                top_n=args.top,
                max_years=args.years,
                data_dir=args.data_dir,
                sort_by=args.sort_by,
                fetch_pages=args.fetch_pages
            )
            analyze_data(
                max_years=args.years,
                data_dir=args.data_dir,
                output_dir=args.output_dir
            )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/]")
        raise


if __name__ == "__main__":
    main()
