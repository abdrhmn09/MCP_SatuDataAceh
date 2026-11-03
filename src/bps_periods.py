"""Discover BPS period IDs from metadata, without calendar-to-ID guesses."""
import asyncio
import re
import httpx

from . import bps_api


async def discover_periods(reader, domain, variable, key):
    periods = {}
    report = {'status': 'not_verified', 'metadata_complete': False, 'pages_checked': [], 'periods_requested': [], 'note': 'Periode yang ditemukan tidak membuktikan seluruh rilis BPS sudah diperiksa.'}
    try:
        async with asyncio.timeout(18):
            queue = [1]
            while queue and len(report['pages_checked']) < 3:
                page = queue.pop(0)
                url, _, headers = bps_api.build_request('listPeriods', {'domain': domain, 'var': int(variable), 'page': page}, key)
                payload = await reader(url, headers)
                if not isinstance(payload, dict) or str(payload.get('status', '')).lower() == 'error': break
                data = payload.get('data')
                if not isinstance(data, list) or len(data) != 2 or not isinstance(data[0], dict) or not isinstance(data[1], list): break
                pages = int(data[0].get('pages', 0))
                report['pages_checked'].append(page)
                for row in data[1]:
                    if not isinstance(row, dict): continue
                    code, label = str(row.get('th_id', '')), str(row.get('th', ''))
                    if re.fullmatch(r'\d+', code) and re.fullmatch(r'(?:19|20)\d{2}', label): periods[code] = label
                if page == 1:
                    queue = list(range(2, pages + 1)) if 1 <= pages <= 3 else [pages, pages - 1] if pages > 3 else []
                report['metadata_complete'] = pages > 0 and len(set(report['pages_checked'])) == pages
    except (ValueError, TypeError, TimeoutError, OSError, httpx.HTTPError):
        pass
    report['status'] = 'metadata_checked' if report['metadata_complete'] else 'partial_metadata' if periods else 'not_verified'
    return [code for code, label in sorted(periods.items(), key=lambda pair: pair[1], reverse=True)[:3]], report
