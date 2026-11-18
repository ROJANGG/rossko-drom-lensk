"""Exact reviewed belt scope; no API calls or publication on import."""
import hashlib
import json
import re
from urllib.parse import urlparse

SCOPE_SHA256 = '44669d31474885bb90ceaa49ce89eba747296ad6ee9339d3a8a261e774da47c0'
APPROVED_SCOPES = {'143b7aec825e75f0000930902f7e26edf3b367c7d5b396f07b50286647fc2d40': 2, SCOPE_SHA256: 85, 'eee1e6bbef4c58bb405e32ec53adef48801b955671a38016783beb19a7bd7140': 82}
CATEGORY = 'Ремни приводные'
ENGINE_TYPE = 'Приводные ремни, натяжители'


def load_reviewed_belts(path):
    manifest = json.loads(path.read_text(encoding='utf-8'))
    records = manifest['items']
    if manifest.get('scope_sha256') not in APPROVED_SCOPES or len(records) != APPROVED_SCOPES[manifest['scope_sha256']]:
        raise ValueError('Unexpected reviewed belt count')
    keys = [r['brand'].casefold() + '|' + r['article'].casefold() for r in records]
    digest = hashlib.sha256('\n'.join(sorted(keys)).encode()).hexdigest()
    if len(set(keys)) != len(records) or digest not in APPROVED_SCOPES or manifest['scope_sha256'] != digest:
        raise ValueError('Reviewed belt scope changed')
    images = set()
    for r in records:
        page = urlparse(r['manufacturer_page'])
        fitment = urlparse(r['fitment_page'])
        photo = urlparse(r['photo_url'])
        if (r['brand'] != 'LYNXauto' or r['category'] != CATEGORY
                or page.scheme != 'https' or page.hostname != 'ecatalogue.lynxauto.jp'
                or page.path != '/' + r['article'] + '.html'
                or fitment.scheme != 'https' or fitment.hostname != page.hostname
                or photo.scheme != 'https' or photo.hostname != page.hostname
                or not r['exact_sku_verified'] or not r['fitment']
                or not re.fullmatch(r'[A-Z0-9]+', r['oem'])
                or r['photo_review'] != 'ACTUAL_EXACT_PRODUCT_PHOTO_VERIFIED'
                or not re.fullmatch(r'[a-f0-9]{64}', r['photo_sha256'])
                or r['photo_sha256'] in images or min(r['photo_dimensions']) < 200):
            raise ValueError('Unverified exact belt evidence')
        images.add(r['photo_sha256'])
    return records


def belt_sku(ad, approved, key):
    """Accept a belt title only when the exact SKU and classification agree."""
    match = re.fullmatch(r'Ремень приводной (LYNXauto) ([A-Za-z0-9.+/\-]+) новый', ad.findtext('Title', ''))
    if (not match or ad.findtext('Brand') != match.group(1)
            or ad.findtext('SparePartType') != 'Двигатель'
            or ad.findtext('EngineSparePartType') != ENGINE_TYPE):
        raise ValueError('Unrecognized reviewed belt title or classification')
    sku = key(match.group(1), match.group(2))
    if approved.get(sku) != CATEGORY:
        raise ValueError('Belt outside reviewed exact SKU scope')
    return sku, CATEGORY

