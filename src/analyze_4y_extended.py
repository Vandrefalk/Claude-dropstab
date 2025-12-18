#!/usr/bin/env python3
"""
Extended Analyzer: Projects with fund investments (last 4 years) + token sale prices.

Features:
- 4 years of investment data
- All funds (not limited)
- Token sale price / pre-valuation data
- ICO price from coin details
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


def analyze_investments_extended(
    data_dir: str = "API data/raw",
    output_dir: str = "API data/analysis_4y",
    years: int = 4
):
    """
    Extended analysis: projects with funds, amounts, valuations, and market cap.

    Args:
        data_dir: Directory with raw API data
        output_dir: Directory for analysis output
        years: Number of years to look back (default 4)
    """
    data_path = Path(data_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Calculate cutoff date
    cutoff_date = datetime.now() - timedelta(days=365 * years)
    print(f"Filtering investments from: {cutoff_date.strftime('%Y-%m-%d')} ({years} years)")

    # Load data
    print("Loading data...")

    # Load coin details for market cap and ICO price
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

    # Build lookups from coin details
    market_caps = {}
    prices = {}
    coin_names = {}
    ico_prices = {}

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

            ico_price = data.get('icoPrice', {})
            if isinstance(ico_price, dict) and ico_price.get('USD'):
                ico_prices[slug] = ico_price.get('USD')

    print(f"Found market caps for {len([v for v in market_caps.values() if v])} coins")
    print(f"Found ICO prices for {len(ico_prices)} coins")

    # Process funding rounds - aggregate by project
    projects = defaultdict(lambda: {
        'name': '',
        'symbol': '',
        'category': '',
        'funds': defaultdict(lambda: {
            'name': '',
            'amount': 0,
            'rounds': [],
            'tier': None,
            'venture_type': None
        }),
        'total_invested': 0,
        'market_cap': None,
        'price': None,
        'ico_price': None,
        'rounds_count': 0,
        'valuations': []  # Store all pre-valuations
    })

    rounds_processed = 0
    rounds_filtered = 0

    for round_data in funding_rounds:
        # Parse date
        date_str = round_data.get('date') or round_data.get('announcedDate')
        if not date_str:
            continue

        try:
            if 'T' in date_str:
                round_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            else:
                round_date = datetime.strptime(date_str, '%Y-%m-%d')
        except:
            continue

        # Filter by date
        if round_date.replace(tzinfo=None) < cutoff_date:
            rounds_filtered += 1
            continue

        rounds_processed += 1

        # Get project info
        project_slug = round_data.get('coinSlug', '')
        project_symbol = round_data.get('coinSymbol', '')

        if not project_slug:
            continue

        # Get investors
        investors = round_data.get('investors', [])
        if not investors:
            continue

        # Get round details
        round_amount = round_data.get('fundsRaised') or 0
        stage = round_data.get('stage', '')
        category = round_data.get('category', '')
        pre_valuation = round_data.get('preValuation')

        # Update project info
        proj = projects[project_slug]
        if not proj['name']:
            proj['name'] = coin_names.get(project_slug, project_symbol or project_slug)
        proj['symbol'] = project_symbol or proj['symbol']
        proj['category'] = category or proj['category']
        proj['market_cap'] = market_caps.get(project_slug)
        proj['price'] = prices.get(project_slug)
        proj['ico_price'] = ico_prices.get(project_slug)
        proj['rounds_count'] += 1

        if pre_valuation:
            proj['valuations'].append({
                'date': date_str[:10],
                'stage': stage,
                'valuation': pre_valuation
            })

        # Process each investor
        for investor in investors:
            if not isinstance(investor, dict):
                continue

            fund_slug = investor.get('investorSlug') or investor.get('slug', '')
            fund_name = investor.get('name', '')
            fund_tier = investor.get('tier')
            venture_type = investor.get('ventureType')

            if not fund_slug:
                continue

            # Calculate investor's share of this round
            inv_amount = round_amount / len(investors) if round_amount and len(investors) > 0 else 0

            fund = proj['funds'][fund_slug]
            fund['name'] = fund_name
            fund['amount'] += inv_amount
            fund['tier'] = fund_tier or fund['tier']
            fund['venture_type'] = venture_type or fund['venture_type']
            fund['rounds'].append({
                'date': date_str[:10],
                'stage': stage,
                'amount': inv_amount,
                'pre_valuation': pre_valuation
            })
            proj['total_invested'] += inv_amount

    print(f"Processed {rounds_processed} rounds (filtered out {rounds_filtered} older than {years} years)")
    print(f"Found {len(projects)} projects with investments")

    # Convert to list and calculate metrics
    result = []
    for slug, proj_data in projects.items():
        funds_list = []
        for fund_slug, fund_info in proj_data['funds'].items():
            funds_list.append({
                'slug': fund_slug,
                'name': fund_info['name'],
                'invested': fund_info['amount'],
                'tier': fund_info['tier'],
                'venture_type': fund_info['venture_type'],
                'rounds': fund_info['rounds']
            })

        # Sort funds by amount invested (descending)
        funds_list.sort(key=lambda x: x['invested'], reverse=True)

        # Calculate metrics
        mcap = proj_data['market_cap']
        total_inv = proj_data['total_invested']
        invest_mcap_ratio = (total_inv / mcap) if (mcap and mcap > 0 and total_inv) else None

        # Get earliest and latest valuations
        valuations = sorted(proj_data['valuations'], key=lambda x: x['date']) if proj_data['valuations'] else []
        first_valuation = valuations[0]['valuation'] if valuations else None
        last_valuation = valuations[-1]['valuation'] if valuations else None

        # Calculate ROI from ICO price
        current_price = proj_data['price']
        ico_price = proj_data['ico_price']
        ico_roi = (current_price / ico_price) if (current_price and ico_price and ico_price > 0) else None

        result.append({
            'project_slug': slug,
            'project_name': proj_data['name'],
            'project_symbol': proj_data['symbol'],
            'category': proj_data['category'],
            'market_cap': mcap,
            'price': current_price,
            'ico_price': ico_price,
            'ico_roi': ico_roi,
            'total_invested': total_inv,
            'invest_mcap_ratio': invest_mcap_ratio,
            'first_valuation': first_valuation,
            'last_valuation': last_valuation,
            'funds_count': len(funds_list),
            'rounds_count': proj_data['rounds_count'],
            'funds': funds_list
        })

    # Sort by market cap
    result.sort(key=lambda x: (x['market_cap'] is None, -(x['market_cap'] or 0)))

    # Save JSON
    json_path = output_path / "projects_funds_4y.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"Saved JSON: {json_path}")

    # Save detailed CSV (one row per project-fund)
    csv_path = output_path / "projects_funds_4y_detailed.csv"
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'project_slug', 'project_name', 'symbol', 'category',
            'market_cap_usd', 'price_usd', 'ico_price_usd', 'ico_roi',
            'total_invested', 'invest_mcap_ratio',
            'funds_count', 'fund_slug', 'fund_name', 'fund_tier', 'fund_invested',
            'fund_round_date', 'fund_round_stage', 'fund_round_valuation'
        ])

        for proj in result:
            for fund in proj['funds']:
                # Get fund's first round info (entry point)
                rounds = fund.get('rounds', [])
                if rounds:
                    first_round = sorted(rounds, key=lambda x: x['date'])[0]
                    round_date = first_round.get('date', '')
                    round_stage = first_round.get('stage', '')
                    round_valuation = first_round.get('pre_valuation', '')
                else:
                    round_date = ''
                    round_stage = ''
                    round_valuation = ''

                writer.writerow([
                    proj['project_slug'],
                    proj['project_name'],
                    proj['project_symbol'],
                    proj['category'],
                    proj['market_cap'] or '',
                    proj['price'] or '',
                    proj['ico_price'] or '',
                    f"{proj['ico_roi']:.2f}x" if proj['ico_roi'] else '',
                    proj['total_invested'],
                    proj['invest_mcap_ratio'] or '',
                    proj['funds_count'],
                    fund['slug'],
                    fund['name'],
                    fund['tier'] or '',
                    fund['invested'],
                    round_date,
                    round_stage,
                    round_valuation
                ])
    print(f"Saved detailed CSV: {csv_path}")

    # Save summary CSV (one row per project)
    summary_path = output_path / "projects_summary_4y.csv"
    with open(summary_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'project_slug', 'project_name', 'symbol', 'category',
            'market_cap_usd', 'price_usd', 'ico_price_usd', 'ico_roi',
            'total_invested', 'invest_mcap_ratio', 'first_valuation', 'last_valuation',
            'funds_count', 'top_funds'
        ])

        for proj in result:
            top_funds = '; '.join([
                f"{fund['name']} (${fund['invested']:,.0f})" if fund['invested'] else fund['name']
                for fund in proj['funds'][:5]
            ])

            writer.writerow([
                proj['project_slug'],
                proj['project_name'],
                proj['project_symbol'],
                proj['category'],
                proj['market_cap'] or '',
                proj['price'] or '',
                proj['ico_price'] or '',
                f"{proj['ico_roi']:.2f}x" if proj['ico_roi'] else '',
                proj['total_invested'],
                proj['invest_mcap_ratio'] or '',
                proj['first_valuation'] or '',
                proj['last_valuation'] or '',
                proj['funds_count'],
                top_funds
            ])
    print(f"Saved summary: {summary_path}")

    # Print top 15 by market cap
    print("\n" + "="*90)
    print(f"TOP 15 PROJECTS BY MARKET CAP (invested in last {years} years)")
    print("="*90)

    for i, proj in enumerate(result[:15], 1):
        mcap_str = f"${proj['market_cap']:,.0f}" if proj['market_cap'] else "N/A"
        invested_str = f"${proj['total_invested']:,.0f}" if proj['total_invested'] else "N/A"
        ico_roi_str = f"{proj['ico_roi']:.2f}x" if proj['ico_roi'] else "N/A"

        print(f"\n{i}. {proj['project_name']} ({proj['project_symbol']}) - {proj['category']}")
        print(f"   Market Cap: {mcap_str}")
        print(f"   Total Invested: {invested_str} from {proj['funds_count']} funds")
        print(f"   ICO Price: ${proj['ico_price']:.4f}" if proj['ico_price'] else "   ICO Price: N/A")
        print(f"   ICO ROI: {ico_roi_str}")
        if proj['first_valuation']:
            print(f"   Valuations: ${proj['first_valuation']:,.0f} → ${proj['last_valuation']:,.0f}" if proj['last_valuation'] else f"   Valuation: ${proj['first_valuation']:,.0f}")
        print(f"   Top Funds:")
        for fund in proj['funds'][:3]:
            tier_str = f" [{fund['tier']}]" if fund['tier'] else ""
            amount_str = f"${fund['invested']:,.0f}" if fund['invested'] else "N/A"
            print(f"     - {fund['name']}{tier_str}: {amount_str}")

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extended project investment analysis")
    parser.add_argument("--data-dir", default="API data/raw", help="Raw data directory")
    parser.add_argument("--output-dir", default="API data/analysis_4y", help="Output directory")
    parser.add_argument("--years", type=int, default=4, help="Years to look back")

    args = parser.parse_args()

    analyze_investments_extended(args.data_dir, args.output_dir, args.years)
