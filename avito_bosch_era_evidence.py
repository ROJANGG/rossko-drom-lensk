"""Exact Bosch identity from reviewed primary catalogue facts and ROSSKO IDs.

No prices, credentials or requests to supplier product pages. Original PDF
hashes/page references and the supplier mapping remain auditable in each proof.
"""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from PIL import Image

BOSCH_PDF = 'https://www.boschautoparts.com/o/commerce-media/accounts/-1/attachments/9469181?download=true'
ERA_PDF = 'https://www.eraspares.de/wp-content/uploads/2022/08/Catalogo_istituzionale_candelette_EN.pdf'


def canon(value):
    return re.sub('[^A-Z0-9]', '', str(value).upper())


def validate_proof(record, proof, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = datetime.fromisoformat(proof['verified_at_utc'])
    if stamp.tzinfo is None or not timedelta(0) <= now-stamp <= timedelta(hours=3):
        raise ValueError('Primary Bosch/ERA evidence expired')
    if record['source_kind'] != 'bosch_era' or canon(record['brand']) != 'BOSCH':
        raise ValueError('Wrong manufacturer for Bosch catalogue proof')
    article = canon(record['article'])
    if not (article == canon(proof['bosch_article']) == canon(proof['era_row']['bosch_article'])
            == canon(proof['supplier_photo']['article'])):
        raise ValueError('Bosch/ERA/supplier exact article mismatch')
    if (proof['bosch_pdf']['exact_table_row'].split()[0] != record['article']
            or proof['era_row']['era_article'] != record['era_reference_article']):
        raise ValueError('Primary catalogue row identity mismatch')
    if (canon(record['oem']) != canon(proof['era_row']['oem'])
            or proof['era_row']['oem_make'] not in ('MERCEDES-BENZ', 'VW', 'BMW')):
        raise ValueError('Original automaker OEM reference mismatch')
    if (record['manufacturer_page'] != BOSCH_PDF or proof['bosch_pdf']['url'] != BOSCH_PDF
            or proof['era_pdf']['url'] != ERA_PDF or record['oem_source'] != ERA_PDF):
        raise ValueError('Wrong primary catalogue URL')
    for source in (proof['bosch_pdf'], proof['era_pdf']):
        if not re.fullmatch('[a-f0-9]{64}', source['sha256']) or source['page'] < 1:
            raise ValueError('Missing original PDF hash/page')
    photo = proof['supplier_photo']
    image = record['images'][0]
    nomenclature = record['photo_supplier_nomenclature']
    if (canon(photo['brand']) != 'BOSCH' or photo['nomenclature'] != nomenclature
            or photo['url'] != image['url'] or proof['photo_sha256'] != image['sha256']
            or urlparse(image['url']).hostname != 'imgs.rossko.ru'
            or nomenclature not in urlparse(image['url']).path.split('/')):
        raise ValueError('Supplier nomenclature/photo identity mismatch')
    if any(canon(token) not in canon(' '.join(proof['fitment_models']))
           for token in record['fitment_tokens']):
        raise ValueError('Reviewed catalogue applicability mismatch')


def load_evidence(record, base=None, now=None):
    cache = record['source_cache']
    if not re.fullmatch(r'input/avito-bosch-era-source-cache/[0-9]+\.json', cache['path']):
        raise ValueError('Invalid Bosch evidence path')
    path = (base or Path(__file__).parent)/cache['path']
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != cache['sha256']:
        raise ValueError('Bosch evidence hash mismatch')
    proof = json.loads(raw)
    validate_proof(record, proof, now)
    photo = path.parent/proof['photo_filename']
    if photo.parent != path.parent or hashlib.sha256(photo.read_bytes()).hexdigest() != proof['photo_sha256']:
        raise ValueError('Reviewed supplier photo bytes changed')
    return proof, photo


def verify_supplier_bindings(book, records):
    selected = {(canon(r['brand']), canon(r['article'])): r['photo_supplier_nomenclature']
                for r in records if r['source_kind'] in ('bosch_era', 'tatsumi_rossko')}
    if not selected:
        return
    rows = book.active.iter_rows(values_only=True)
    header = {str(value): index for index, value in enumerate(next(rows))}
    found = {}
    for row in rows:
        key = (canon(row[header['Бренд']]), canon(row[header['Артикул']]))
        if key in selected:
            code = str(row[header['Номенклатура']] or '')
            if code != selected[key]:
                raise ValueError('Fresh supplier nomenclature no longer matches reviewed photo')
            found[key] = code
    if set(found) != set(selected):
        raise ValueError('Reviewed photo SKU missing from fresh supplier workbook')


def prepare_photo(record, place, identifier, public_base):
    _, photo = load_evidence(record)
    with Image.open(photo) as image:
        image.load()
        if (image.format != 'JPEG' or list(image.size) != [record['images'][0]['width'], record['images'][0]['height']]
                or min(image.size) < 200):
            raise ValueError('Reviewed photo size/format mismatch')
    digest = record['images'][0]['sha256']
    name = identifier + '-' + digest[:12] + '.jpg'
    (place/name).write_bytes(photo.read_bytes())
    return {'filename': name, 'sha256': digest, 'public_url': public_base+name,
            'source_verification': 'primary_catalogues_and_exact_supplier_nomenclature_max_3h'}
