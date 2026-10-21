"""Local, non-certifying preparation diagnostics. Never stores document text."""
import re

LIMITATION = ('Automatic flags are review hints, not technical approval. Check the original pages. '
              'Reading order, component ownership and table relationships are not verified. '
              'Restriction hints cover English/Russian; other text changes still need review. No AI is required.')
PATTERNS = {
    'numbers': r'\d+(?:[.,]\d+)*',
    'restrictions': r'(?iu)\b(?:not|no|never|cannot|must|shall|prohibited|нельзя|не|нет|запрещено|должен|должны)\b',
    'units': r'\b(?:bar|kPa|MPa|Pa|psi|mm|cm|km|m|kg|mg|g|Nm|rpm|V|mV|A|mA|W|kW|Hz|kHz|MHz|ohm|бар|кПа|МПа|мм|см|кг|Ом)\b|[°Ωµμ%]',
    'identifiers': r'(?iu)\b(?:[a-zа-я]+[-_]?\d[\w-]*|\d+[a-zа-я][\w-]*)\b',
    'numbered_steps': r'(?m)^\s*(\d+(?:\.\d+)*)[.)]\s+',
}

def changes(old, new):
    if old == new:
        return []
    flags = ['text_changed']
    for key, pattern in PATTERNS.items():
        left, right = re.findall(pattern, old), re.findall(pattern, new)
        if key == 'restrictions':
            left, right = [x.lower() for x in left], [x.lower() for x in right]
        if left != right:
            flags.append(key + '_changed')
    return flags


def metric(number, text, included=True, pdf=False):
    return {'page': number, 'included': included, 'characters': len(text),
            'utf8_bytes': len(text.encode('utf-8')), 'reason': 'included' if included else 'below_100_characters',
            'reading_order': 'not_verified' if pdf else 'not_assessed'}


def source_report(source_id, fingerprint, pages, total_pages, filename, metrics=None, originals=None, chunks=()):
    if type(total_pages) is not int or not 0 <= total_pages <= 10000 or any(not 1 <= p.number <= 10000 for p in pages):
        raise ValueError('Quality report supports at most 10000 original pages per document.')
    pdf = filename.lower().endswith('.pdf')
    included = {p.number: p for p in pages}
    prior = {p.number: p for p in originals or []}
    measured = {m['page']: m for m in metrics or []}
    count = max(total_pages, max(included, default=0))
    records = []
    for n in range(1, count + 1):
        if n in included:
            p = included[n]; row = metric(n, p.text, pdf=pdf)
            row['flags'] = (['sparse_text'] if len(p.text) < 200 else []) + (['pdf_layout_not_verified'] if pdf else [])
            if n in prior:
                row['flags'] += changes(prior[n].text, p.text)
        else:
            row = {'page': n, 'included': False, 'characters': measured.get(n, {}).get('characters'), 'utf8_bytes': measured.get(n, {}).get('utf8_bytes'), 'reason': 'below_100_characters' if n in measured else 'not_in_extracted_text', 'reading_order': 'not_verified' if pdf else 'not_assessed'}
            row['flags'] = ['omitted_page']
        records.append(row)
    return {'format': 'dataeater-source-quality', 'version': 1, 'source_id': source_id,
            'source_sha256': fingerprint, 'total_pages': count, 'pages': records,
            'oversized_passages': [{'page': c.page_start, 'characters': len(c.text)} for c in chunks if len(c.text) > 1200],
            'technical_accuracy': 'not_verified', 'limitations': LIMITATION}


def summary(reports):
    pages = [p for q in reports for p in q.get('pages', [])]
    return ('Preparation quality: %d omitted pages; %d changed pages; %d PDF pages need layout review. '
            'Automatic checks do not verify technical accuracy.' % (
                sum(not p['included'] for p in pages),
                sum('text_changed' in p.get('flags', []) for p in pages),
                sum('pdf_layout_not_verified' in p.get('flags', []) for p in pages)))


def from_sources(sources):
    return [s['preparation_quality'] for s in sources if 'preparation_quality' in s]
