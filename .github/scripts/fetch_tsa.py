"""
Fetches TSA daily checkpoint throughput from tsa.gov and saves to data/tsa.json.
Merges with existing data so history accumulates across runs.
"""
import json, os, sys
from datetime import datetime
import requests
from bs4 import BeautifulSoup

DATA_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'tsa.json')


def fetch_tsa() -> list[dict]:
    resp = requests.get(
        'https://www.tsa.gov/travel/passenger-volumes',
        headers={'User-Agent': 'Mozilla/5.0'},
        timeout=30,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, 'html.parser')
    table = soup.find('table')
    if not table:
        raise RuntimeError('No <table> found on TSA page')

    rows = []
    for tr in table.find('tbody').find_all('tr'):
        cells = tr.find_all('td')
        if len(cells) < 2:
            continue
        date_str  = cells[0].get_text(strip=True)
        count_str = cells[1].get_text(strip=True).replace(',', '')
        try:
            dt    = datetime.strptime(date_str, '%m/%d/%Y')
            count = int(count_str)
            rows.append({'date': dt.strftime('%Y-%m-%d'), 'value': count})
        except (ValueError, TypeError):
            continue

    return sorted(rows, key=lambda r: r['date'])


def main():
    # Load existing data
    existing: dict = {'updated': '', 'data': []}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH) as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                pass

    existing_map = {r['date']: r['value'] for r in existing.get('data', [])}

    print('Fetching TSA data…')
    new_rows = fetch_tsa()

    # Merge: new rows win on conflict
    for r in new_rows:
        existing_map[r['date']] = r['value']

    merged = sorted(
        [{'date': d, 'value': v} for d, v in existing_map.items()],
        key=lambda r: r['date'],
    )

    out = {'updated': datetime.utcnow().isoformat() + 'Z', 'data': merged}
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, 'w') as f:
        json.dump(out, f, separators=(',', ':'))

    print(f'TSA: {len(merged)} records saved (added/updated {len(new_rows)} rows)')


if __name__ == '__main__':
    main()
