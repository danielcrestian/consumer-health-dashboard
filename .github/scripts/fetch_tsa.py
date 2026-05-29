"""
Fetches TSA daily checkpoint throughput from tsa.gov and saves to data/tsa.json.
Merges with existing data so history accumulates across runs.

Note: tsa.gov blocks plain server requests. We try multiple URLs and a
realistic browser User-Agent. If all attempts fail, existing data is preserved
and the script exits cleanly (no workflow failure).
"""
import json, os
from datetime import datetime
import requests
from bs4 import BeautifulSoup

DATA_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'tsa.json')

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

# TSA also publishes the same table at a secondary URL sometimes
URLS = [
    'https://www.tsa.gov/travel/passenger-volumes',
    'https://www.tsa.gov/coronavirus/passenger-throughput',
]


def fetch_tsa() -> list[dict] | None:
    for url in URLS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 403:
                print(f'403 Forbidden from {url} — TSA is blocking server IPs')
                continue
            resp.raise_for_status()

            soup  = BeautifulSoup(resp.text, 'html.parser')
            table = soup.find('table')
            if not table:
                print(f'No <table> found at {url}')
                continue

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

            if rows:
                print(f'Fetched {len(rows)} rows from {url}')
                return sorted(rows, key=lambda r: r['date'])

        except requests.RequestException as e:
            print(f'Request error for {url}: {e}')
            continue

    return None   # all attempts failed


def main():
    # Load existing data
    existing = {'updated': '', 'data': []}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH) as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                pass

    existing_map = {r['date']: r['value'] for r in existing.get('data', [])}

    print('Fetching TSA data…')
    new_rows = fetch_tsa()

    if new_rows is None:
        # TSA blocked us — preserve whatever data we already have
        print('WARNING: Could not fetch TSA data. Keeping existing data unchanged.')
        print('TSA.gov blocks requests from cloud server IPs (GitHub Actions).')
        print('The TSA card in the dashboard will show historical data only.')
        # Exit 0 so the workflow does not fail
        return

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
