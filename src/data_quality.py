"""CSV presentation and conservative coverage checks; never infer absent observations."""
import math
import re

MISSING = {'', 'nan', 'null', 'none', 'na', 'n/a', '-', '...', 'inf', '-inf', '+inf', 'infinity', '-infinity'}
REGIONS = ('nama_wilayah', 'bps_nama_kabupaten_kota', 'kemendagri_nama_kabupaten_kota', 'nama_kabupaten_kota', 'kabupaten_kota', 'wilayah', 'bps_nama_provinsi', 'nama_provinsi')
YEARS = ('tahun', 'thn', 'year', 'th', 'periode', 'waktu')


def clean_cell(value):
    if value is None or isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, str) and value.strip().lower() in MISSING:
        return None
    return value.item() if hasattr(value, 'item') else value


def numeric(value):
    if value is None or isinstance(value, bool): return False
    if isinstance(value, str) and not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', value.strip()): return False
    try: return math.isfinite(float(value))
    except (ValueError, TypeError, OverflowError): return False


def summarize(frame, value_column, limit):
    columns = [str(col) for col in frame.columns]
    cleaned = [[clean_cell(value) for value in row] for row in frame.itertuples(index=False, name=None)]
    rows = [dict(zip(columns, row)) for row in cleaned[:limit]]
    for row in rows:
        if numeric(row.get(value_column)):
            number = float(row[value_column])
            row[value_column] = int(number) if number.is_integer() else number
    missing = {col: sum(row[i] is None for row in cleaned) for i, col in enumerate(columns)}
    index = columns.index(value_column) if value_column in columns else None
    finite = [row for row in cleaned if index is not None and numeric(row[index])]
    year_index = next((i for i, col in enumerate(columns) if col.lower().strip() in YEARS), None)
    years = sorted({match.group(0) for row in finite for match in [re.search(r'\b(?:19|20)\d{2}\b', str(row[year_index]))] if match}) if year_index is not None else []
    coverage = {}
    coverage['years'] = {'column': columns[year_index] if year_index is not None else None, 'values': years[:100], 'complete': len(years) <= 100}
    for dimension, aliases in [('regions', REGIONS), ('periods', ('periode', 'bulan', 'triwulan', 'semester')), ('categories', ('kategori', 'jenis_kelamin', 'jenis kelamin'))]:
        col = next((col for alias in aliases for col in columns if col.lower().strip() == alias), None)
        values = sorted({str(row[columns.index(col)]).strip().lower() for row in finite if row[columns.index(col)] is not None}) if col else []
        coverage[dimension] = {'column': col, 'values': values[:100], 'complete': len(values) <= 100}
    return {
        'columns': columns, 'rows': rows, 'returned_rows': len(rows), 'total_rows': len(cleaned), 'truncated': len(rows) < len(cleaned),
    }, {
        'missing_by_column': missing, 'missing_cells': sum(missing.values()), 'value_column': value_column or None,
        'finite_value_count': len(finite), 'missing_value_count': missing.get(value_column) if value_column else None,
        'non_numeric_value_count': sum(row[index] is not None and not numeric(row[index]) for row in cleaned) if index is not None else None,
        'latest_value_year': years[-1] if years else None,
    }, coverage


def audit_coverage(left, right):
    if not left or not right or not left.quality or not right.quality:
        return False, 'Metadata observasi belum tersedia untuk memeriksa wilayah, periode, dan nilai.'
    if not left.quality['finite_value_count'] or not right.quality['finite_value_count']:
        return False, 'Salah satu sumber tidak memiliki nilai indikator numerik yang dapat dipastikan.'
    for dimension in ('regions', 'years', 'periods', 'categories'):
        a, b = (result.coverage.get(dimension, {}) for result in (left, right))
        if not a.get('complete') or not b.get('complete'):
            return False, 'Cakupan dimensi terlalu besar untuk diverifikasi dalam audit ringkas.'
        if dimension in {'regions','years'} and (not a.get('values') or not b.get('values')):
            return False, 'Cakupan wilayah atau tahun pada baris observasi belum dapat dipastikan.'
        if a.get('values') != b.get('values'):
            return False, f'Cakupan {dimension} berbeda atau belum lengkap. Angka tidak dibandingkan langsung.'
    return True, 'Cakupan wilayah, subperiode, kategori, dan keberadaan nilai telah diperiksa; kesamaan angka dan metodologi belum dibuktikan.'
