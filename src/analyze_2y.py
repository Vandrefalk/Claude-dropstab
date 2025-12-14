#!/usr/bin/env python3
"""
Analyzer: Projects with fund investments (last 2 years) and market cap.

Output format per project:
- Project name
- Funds that invested (last 2 years)
- Amount from each fund
- Total investment
- Current market cap
"""

import json
import csv
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict


def load_json(path: str) -> dict | list | None:
    """Load JSON file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return None


def analyze_investments(data_dir: str = "API data/raw", output_dir: str = "API data/analysis"):
    """
    Analyze investments: projects with funds, amounts, and market cap.

    Args:
        data_dir: Directory with raw API data
        output_dir: Directory for analysis output
    """
    data_path = Path(data_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Calculate date 2 years ago
    two_years_ago = datetime.now() - timedelta(days=365 * 2)
    print(f"Filtering investments from: {two_years_ago.strftime('%Y-%m-%d')}")

    # Load data
    print("Loading data...")

    # Load coin details for market cap
    coin_details = load_json(data_path / "coin_details.json")
    if not coin_details:
        print("ERROR: Could not load coin_details.json")
        return

    # Load funding rounds
    funding_rounds = load_json(data_path / "funding_rounds_raw.json")
    if not funding_rounds:
        print("ERROR: Could not load funding_rounds_raw.json")
        return

    print(f"Loaded {len(coin_details)} coins, {len(funding_rounds)} funding rounds")

    # Build market cap lookup by slug
    market_caps = {}
    prices = {}
    coin_names = {}

    for slug, coin_data in coin_details.items():
        if coin_data.get('status') == 'OK' and coin_data.get('data'):
            data = coin_data['data']
            coin_names[slug] = data.get('name', '')
            mcap = data.get('marketCap', {})
            if isinstance(mcap, dict):
                market_caps[slug] = mcap.get('USD')
            price_data = data.get('price', {})
            if isinstance(price_data, dict):
                prices[slug] = price_data.get('USD')

    print(f"Found market caps for {len([v for v in market_caps.values() if v])} coins")

    # Process funding rounds - aggregate by project
    # Structure: {project_slug: {fund_slug: total_amount, ...}}
    projects = defaultdict(lambda: {
        'name': '',
        'funds': defaultdict(lambda: {'name': '', 'amount': 0, 'rounds': []}),
        'total_invested': 0,
        'market_cap': None,
        'price': None,
        'rounds_count': 0
    })

    rounds_processed = 0
    rounds_filtered = 0

    for round_data in funding_rounds:
        # Parse date
        date_str = round_data.get('date') or round_data.get('announcedDate')
        if not date_str:
            continue

        try:
            # Handle different date formats
            if 'T' in date_str:
                round_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            else:
                round_date = datetime.strptime(date_str, '%Y-%m-%d')
        except:
            continue

        # Filter by date (last 2 years)
        if round_date.replace(tzinfo=None) < two_years_ago:
            rounds_filtered += 1
            continue

        rounds_processed += 1

        # Get project info - API uses coinSlug directly, not nested coin object
        project_slug = round_data.get('coinSlug', '')
        project_name = round_data.get('coinSymbol', '')

        if not project_slug:
            continue

        # Get investors
        investors = round_data.get('investors', [])
        if not investors:
            continue

        # Get round amount - API uses fundsRaised
        round_amount = round_data.get('fundsRaised') or round_data.get('amount') or 0
        stage = round_data.get('stage', '')
        category = round_data.get('category', '')

        # Update project info
        if not projects[project_slug]['name']:
            projects[project_slug]['name'] = project_name or coin_names.get(project_slug, project_slug)
        projects[project_slug]['market_cap'] = market_caps.get(project_slug)
        projects[project_slug]['price'] = prices.get(project_slug)
        projects[project_slug]['rounds_count'] += 1

        # Process each investor in this round
        for investor in investors:
            if isinstance(investor, dict):
                # API uses investorSlug, not slug
                fund_slug = investor.get('investorSlug') or investor.get('slug', '')
                fund_name = investor.get('name', '')
                # Individual investor amount if available, otherwise divide round equally
                inv_amount = investor.get('amount') or (round_amount / len(investors) if round_amount and len(investors) > 0 else 0)
            else:
                continue

            if fund_slug:
                projects[project_slug]['funds'][fund_slug]['name'] = fund_name
                projects[project_slug]['funds'][fund_slug]['amount'] += inv_amount
                projects[project_slug]['funds'][fund_slug]['rounds'].append({
                    'date': date_str[:10],
                    'stage': stage,
                    'amount': inv_amount
                })
                projects[project_slug]['total_invested'] += inv_amount

    print(f"Processed {rounds_processed} rounds (filtered out {rounds_filtered} older than 2 years)")
    print(f"Found {len(projects)} projects with investments in last 2 years")

    # Convert to list and sort by market cap (descending)
    result = []
    for slug, proj_data in projects.items():
        funds_list = []
        for fund_slug, fund_info in proj_data['funds'].items():
            funds_list.append({
                'slug': fund_slug,
                'name': fund_info['name'],
                'invested': fund_info['amount'],
                'rounds': fund_info['rounds']
            })

        # Sort funds by amount invested (descending)
        funds_list.sort(key=lambda x: x['invested'], reverse=True)

        result.append({
            'project_slug': slug,
            'project_name': proj_data['name'],
            'market_cap': proj_data['market_cap'],
            'price': proj_data['price'],
            'total_invested': proj_data['total_invested'],
            'funds_count': len(funds_list),
            'rounds_count': proj_data['rounds_count'],
            'funds': funds_list
        })

    # Sort by market cap (projects with market cap first, then by value)
    result.sort(key=lambda x: (x['market_cap'] is None, -(x['market_cap'] or 0)))

    # Save JSON
    json_path = output_path / "projects_funds_2y.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"Saved JSON: {json_path}")

    # Save CSV (flattened - one row per project-fund combination)
    csv_path = output_path / "projects_funds_2y.csv"
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'project_slug', 'project_name', 'market_cap_usd', 'price_usd',
            'total_invested', 'funds_count',
            'fund_slug', 'fund_name', 'fund_invested'
        ])

        for proj in result:
            for fund in proj['funds']:
                writer.writerow([
                    proj['project_slug'],
                    proj['project_name'],
                    proj['market_cap'] or '',
                    proj['price'] or '',
                    proj['total_invested'],
                    proj['funds_count'],
                    fund['slug'],
                    fund['name'],
                    fund['invested']
                ])
    print(f"Saved CSV: {csv_path}")

    # Save summary CSV (one row per project)
    summary_path = output_path / "projects_summary_2y.csv"
    with open(summary_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'project_slug', 'project_name', 'market_cap_usd', 'price_usd',
            'total_invested', 'funds_count', 'top_funds'
        ])

        for proj in result:
            # Top 5 funds as string
            top_funds = '; '.join([
                f"{fund['name']} (${fund['invested']:,.0f})" if fund['invested'] else fund['name']
                for fund in proj['funds'][:5]
            ])

            writer.writerow([
                proj['project_slug'],
                proj['project_name'],
                proj['market_cap'] or '',
                proj['price'] or '',
                proj['total_invested'],
                proj['funds_count'],
                top_funds
            ])
    print(f"Saved summary: {summary_path}")

    # Print top 10 by market cap
    print("\n" + "="*80)
    print("TOP 10 PROJECTS BY MARKET CAP (invested in last 2 years)")
    print("="*80)

    for i, proj in enumerate(result[:10], 1):
        mcap_str = f"${proj['market_cap']:,.0f}" if proj['market_cap'] else "N/A"
        invested_str = f"${proj['total_invested']:,.0f}" if proj['total_invested'] else "N/A"

        print(f"\n{i}. {proj['project_name']} ({proj['project_slug']})")
        print(f"   Market Cap: {mcap_str}")
        print(f"   Total Invested: {invested_str} from {proj['funds_count']} funds")
        print(f"   Top Funds:")
        for fund in proj['funds'][:3]:
            amount_str = f"${fund['invested']:,.0f}" if fund['invested'] else "N/A"
            print(f"     - {fund['name']}: {amount_str}")

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze project investments (last 2 years)")
    parser.add_argument("--data-dir", default="API data/raw", help="Raw data directory")
    parser.add_argument("--output-dir", default="API data/analysis", help="Output directory")

    args = parser.parse_args()

    analyze_investments(args.data_dir, args.output_dir)
