"""
Fetches all FRED economic series used by the Consumer Health Dashboard
and saves to data/fred.json.  Requires FRED_API_KEY environment variable.
"""
import json, os, sys
import requests
from datetime import datetime, timezone

DATA_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'fred.json')
FRED_URL  = 'https://api.stlouisfed.org/fred/series/observations'

API_KEY = os.environ.get('FRED_API_KEY', '').strip()

# metric_id → FRED series ID
SERIES = {
    'cc_util':   'RCCCBACTIVEUTILPCT50',   # Credit card utilization (median)
    'savings':   'PSAVERT',                 # Personal saving rate
    'dsr':       'TDSP',                    # Household debt service ratio
    'rdpi':      'DSPIC96',                 # Real disposable personal income
    'wages':     'LES1252881600Q',          # Real median usual weekly earnings
    'claims':    'IC4WSA',                  # Initial claims (4-wk avg)
    'sentiment': 'UMCSENT',                 # U of Michigan consumer sentiment
    'retail':    'MRTSSM44W72USS',          # Retail ex-auto & gas
    'lh_emp':    'USLAH',                   # Leisure & hospitality employment
}

HEADERS = {'User-Agent': 'consumer-health-dashboard/1.0'}


def fetch_series(sid):
    params = {
        'series_id':         sid,
        'api_key':           API_KEY,
        'file_type':         'json',
        'limit':             2000,           # weekly series can have 1800+ points
        'sort_order':        'asc',
        'observation_start': '1990-01-01',   # 35+ yrs of history is plenty
    }
    r = requests.get(FRED_URL, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    j = r.json()
    if 'error_message' in j:
        raise RuntimeError(f'FRED API error for {sid}: {j["error_message"]}')
    pts = [
        {'date': o['date'], 'value': round(float(o['value']), 4)}
        for o in j['observations']
        if o['value'] != '.'
    ]
    return pts


def main():
    if not API_KEY:
        print('ERROR: FRED_API_KEY environment variable is not set.')
        print('Add it as a GitHub Actions secret named FRED_API_KEY.')
        sys.exit(1)

    out = {'updated': datetime.now(timezone.utc).isoformat()}
    failed = []

    for key, sid in SERIES.items():
        print(f'Fetching {key} ({sid})…', end=' ', flush=True)
        try:
            pts = fetch_series(sid)
            out[key] = pts
            print(f'{len(pts)} records  [{pts[0]["date"]} … {pts[-1]["date"]}]' if pts else '0 records')
        except Exception as e:
            print(f'FAILED — {e}')
            out[key] = []
            failed.append(key)

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, 'w') as f:
        json.dump(out, f, separators=(',', ':'))

    total = sum(len(v) for k, v in out.items() if k != 'updated')
    print(f'\nSaved {total} total observations to {DATA_PATH}')

    if failed:
        print(f'WARNING: {len(failed)} series failed: {", ".join(failed)}')
        # Don't exit 1 — partial data is still useful
    if total == 0:
        raise RuntimeError('All FRED series returned 0 records — check API key.')


if __name__ == '__main__':
    main()
