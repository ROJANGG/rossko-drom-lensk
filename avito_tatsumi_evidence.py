"""Reviewed TATSUMI manufacturer OES/fitment and exact ROSSKO product photo."""
import hashlib
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
from PIL import Image
from avito_bosch_era_evidence import canon


def validate_proof(record, proof, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = datetime.fromisoformat(proof['verified_at_utc'])
    if stamp.tzinfo is None or not timedelta(0) <= now-stamp <= timedelta(hours=3):
        raise ValueError('TATSUMI source review expired')
    article = record['article']
    manufacturer = proof['manufacturer']
    photo = proof['supplier_photo']
    if record['source_kind'] != 'tatsumi_rossko' or canon(record['brand']) != 'TATSUMI':
        raise ValueError('Wrong reviewed manufacturer')
    if not re.fullmatch('THQ[0-9]{4}', article):
        raise ValueError('Wrong exact article')
    primary = 'https://tatsumi.ru/catalog/'+article.lower()+'/'
    if (record['manufacturer_page'] != primary or record['oem_source'] != primary
            or manufacturer['url'] != primary or manufacturer['groups']['Артикул'] != article
            or photo['article'] != article or photo['brand'] != 'TATSUMI'):
        raise ValueError('Manufacturer/supplier article mismatch')
    if record['oem'] != manufacturer['groups']['OES Номер']:
        raise ValueError('Manufacturer OES mismatch')
    if not re.fullmatch('[a-f0-9]{64}', manufacturer['html_sha256']):
        raise ValueError('Missing original manufacturer capture hash')
    fits = manufacturer['fitment']
    if not fits or any(len(row) != 7 for row in fits):
        raise ValueError('Missing manufacturer fitment rows')
    if record['fitment_tokens'] != [row[0]+' '+row[1]+'; '+row[3]+'; '+row[4] for row in fits[:3]]:
        raise ValueError('Reviewed fitment differs from source')
    if any(token not in record['fitment'] for token in record['fitment_tokens']):
        raise ValueError('Listing fitment differs from review')
    image = record['images'][0]
    code = record['photo_supplier_nomenclature']
    expected_card = 'https://rossko.ru/card/tatsumi-'+article.lower()+'-'+code.lower()+'/'
    if (photo['nomenclature'] != code or photo['card_url'] != expected_card
            or photo['url'] != image['url'] or photo['sha256'] != image['sha256']
            or photo['dimensions'] != [image['width'], image['height']]
            or urlparse(image['url']).hostname != 'imgs.rossko.ru'
            or code not in urlparse(image['url']).path.split('/')
            or min(photo['dimensions']) < 200):
        raise ValueError('Reviewed supplier photo identity mismatch')


def load_evidence(record, base=None, now=None):
    cache = record['source_cache']
    if not re.fullmatch(r'input/avito-tatsumi-source-cache/THQ[0-9]{4}\.json', cache['path']):
        raise ValueError('Invalid TATSUMI evidence path')
    raw = ((base or Path(__file__).parent)/cache['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != cache['sha256']:
        raise ValueError('TATSUMI proof changed')
    proof = json.loads(raw)
    validate_proof(record, proof, now)
    return proof


def prepare_photo(record, place, identifier, public_base):
    proof = load_evidence(record)
    response = requests.get(proof['supplier_photo']['url'], headers={'Referer': 'https://rossko.ru/'}, timeout=(10,35))
    response.raise_for_status()
    raw = response.content
    digest = record['images'][0]['sha256']
    if len(raw) > 8_000_000 or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Supplier photo bytes differ from reviewed original')
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        if image.format != 'JPEG' or list(image.size) != proof['supplier_photo']['dimensions']:
            raise ValueError('Supplier photo dimensions/format mismatch')
    name = identifier+'-'+digest[:12]+'.jpg'
    (place/name).write_bytes(raw)
    return {'filename':name,'sha256':digest,'public_url':public_base+name,
            'source_verification':'manufacturer_OES_fitment_and_exact_supplier_photo_max_3h'}
