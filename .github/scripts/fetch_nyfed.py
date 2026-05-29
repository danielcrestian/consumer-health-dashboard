"""
Downloads the latest NY Fed Household Debt & Credit quarterly Excel file
and extracts "Percent of Balance 90+ Days Delinquent" by loan type.
Saves to data/delinquency.json.

NY Fed Excel URL pattern:
  https://www.newyorkfed.org/medialibrary/interactives/householdcredit/data/xls/hhd_c_report_YYYYqN.xlsx
"""
import io, json, os, re
from datetime import datetime

import openpyxl
import requests

DATA_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'delinquency.json')
BASE_URL  = 'https://www.newyorkfed.org/medialibrary/interactives/householdcredit/data/xls'


# ── helpers ──────────────────────────────────────────────────────────────────

def quarter_sequence(start_year: int, start_q: int, steps: int = 6):
    """Yield (year, quarter) going backwards from start."""
    y, q = start_year, start_q
    for _ in range(steps):
        yield y, q
        q -= 1
        if q < 1:
            q, y = 4, y - 1


def download_latest() -> tuple[bytes, str]:
    now = datetime.utcnow()
    for y, q in quarter_sequence(now.year, (now.month - 1) // 3 + 1):
        url = f'{BASE_URL}/hhd_c_report_{y}q{q}.xlsx'
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                print(f'Downloaded: {url}')
                return r.content, url
        except requests.RequestException:
            continue
    raise RuntimeError('Could not find NY Fed Excel file for last 6 quarters')


def find_delinquency_sheet(wb: openpyxl.Workbook) -> openpyxl.worksheet.worksheet.Worksheet:
    """
    Locate the sheet containing percent-of-balance 90+ day delinquency data.
    The NY Fed typically labels this sheet something like 'Page 11 Data'.
    We search by name first, then by cell content.
    """
    keywords = ['delinquent', '90', 'page 11', 'fig 11', 'figure 11']

    # 1. Search sheet names
    for name in wb.sheetnames:
        if any(kw in name.lower() for kw in keywords):
            print(f'Sheet found by name: "{name}"')
            return wb[name]

    # 2. Search first few rows of each sheet for header keywords
    for name in wb.sheetnames:
        ws = wb[name]
        for row in ws.iter_rows(min_row=1, max_row=6, values_only=True):
            for cell in row:
                if cell and isinstance(cell, str):
                    low = cell.lower()
                    if '90' in low and 'delinquent' in low:
                        print(f'Sheet found by content scan: "{name}"')
                        return ws

    # 3. Fallback: sheet whose name contains '11'
    for name in wb.sheetnames:
        if '11' in name:
            print(f'Sheet found by fallback (contains "11"): "{name}"')
            return wb[name]

    print(f'WARNING: could not identify sheet. Sheets available: {wb.sheetnames}')
    # Last resort: penultimate sheet (often the right one in recent files)
    return wb[wb.sheetnames[-2]] if len(wb.sheetnames) >= 2 else wb.active


def parse_quarter_date(raw) -> str | None:
    """Convert various NY Fed date formats to ISO YYYY-MM-DD (first day of quarter)."""
    if isinstance(raw, datetime):
        return raw.strftime('%Y-%m-%d')
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    # e.g. "2025:Q1" or "2025:q1"
    m = re.match(r'(\d{4})[:\s-]?[Qq](\d)', raw)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        return f'{y}-{q*3-2:02d}-01'
    # e.g. "Q1 2025"
    m = re.match(r'[Qq](\d)\s+(\d{4})', raw)
    if m:
        q, y = int(m.group(1)), int(m.group(2))
        return f'{y}-{q*3-2:02d}-01'
    # e.g. bare year like "2003" — skip
    return None


def extract_data(ws) -> dict[str, list[dict]]:
    """
    Parse the worksheet and return a dict with keys:
      mortgage, auto, credit_card, student_loan
    each containing [{date, value}, ...] sorted by date.
    """
    col_map: dict[str, int] = {}   # key → 0-based column index
    data: dict[str, list] = {
        'mortgage': [], 'auto': [], 'credit_card': [], 'student_loan': []
    }

    PATTERNS = {
        'mortgage':     ['mortgage'],
        'auto':         ['auto'],
        'credit_card':  ['credit card', 'creditcard', 'credit_card'],
        'student_loan': ['student'],
    }

    header_row_idx = None

    for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
        if not any(c is not None for c in row):
            continue

        # ── detect header row ─────────────────────────────────
        if not col_map:
            row_strs = [str(c).lower().strip() if c is not None else '' for c in row]
            matched = False
            for key, pats in PATTERNS.items():
                for ci, cell_str in enumerate(row_strs):
                    if any(p in cell_str for p in pats):
                        col_map[key] = ci
                        matched = True
            if matched:
                header_row_idx = row_idx
                print(f'Header row {row_idx}: col_map={col_map}')
            continue

        # ── data rows ────────────────────────────────────────
        date_val = row[0]
        date_str = parse_quarter_date(date_val)
        if not date_str:
            continue

        for key, ci in col_map.items():
            if ci >= len(row):
                continue
            raw_val = row[ci]
            if raw_val is None:
                continue
            try:
                val = float(raw_val)
                # NY Fed reports as percentage already (e.g. 3.5 means 3.5%)
                data[key].append({'date': date_str, 'value': round(val, 4)})
            except (ValueError, TypeError):
                continue

    # Sort each series by date
    for key in data:
        data[key].sort(key=lambda r: r['date'])
        print(f'  {key}: {len(data[key])} records')

    return data


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    content, source_url = download_latest()

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    print(f'Sheets: {wb.sheetnames}')

    ws   = find_delinquency_sheet(wb)
    data = extract_data(ws)

    out = {
        'updated': datetime.utcnow().isoformat() + 'Z',
        'source': source_url,
        **data,
    }

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, 'w') as f:
        json.dump(out, f, separators=(',', ':'))

    print(f'Saved to {DATA_PATH}')


if __name__ == '__main__':
    main()
