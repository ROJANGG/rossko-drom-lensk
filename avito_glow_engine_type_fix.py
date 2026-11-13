"""Add the required Avito engine subtype to exact glow-plug ads only.

Byte-preserving migration: no supplier queries, price updates or new ads.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

ENGINE_TYPE = 'Катушка зажигания, свечи, электрика'
TAG = 'EngineSparePartType'
GLOW = re.compile(r'^Свеч[аи]\s+накал', re.I)

def fix_xml(raw):
    root = ET.fromstring(raw)
    if root.tag != 'Ads': raise ValueError('Unexpected XML root')
    ads = root.findall('Ad')
    ids = [a.findtext('Id') for a in ads]
    if None in ids or len(ids)!=len(set(ids)): raise ValueError('Missing/duplicate ad ID')
    changed=[]
    def patch(match):
        block=match.group(0);ad=ET.fromstring(block)
        if ad.findtext('SparePartType')!='Двигатель':return block
        if not GLOW.search(ad.findtext('Title') or ''):raise ValueError('Unknown engine family; manual review needed')
        nodes=ad.findall(TAG)
        if len(nodes)>1:raise ValueError('Duplicate engine subtype')
        if nodes:
            if nodes[0].text!=ENGINE_TYPE:raise ValueError('Unexpected existing engine subtype')
            return block
        anchor=b'</SparePartType>'
        if block.count(anchor)!=1:raise ValueError('Ambiguous spare-part category')
        changed.append(ad.findtext('Id'))
        return block.replace(anchor,anchor+('<'+TAG+'>'+ENGINE_TYPE+'</'+TAG+'>').encode(),1)
    result=re.sub(rb'<Ad>.*?</Ad>',patch,raw,flags=re.S)
    after=ET.fromstring(result)
    if len(after.findall('Ad'))!=len(ads):raise ValueError('Ad count changed')
    for before,new in zip(ads,after.findall('Ad')):
        if before.findtext('Id')!=new.findtext('Id'):raise ValueError('Ad IDs/order changed')
        if before.findtext('Id') in changed:new.remove(new.find(TAG))
        if ET.tostring(before)!=ET.tostring(new):raise ValueError('Non-subtype fields changed')
    return result,changed

def main():
    p=argparse.ArgumentParser();p.add_argument('--live',type=Path,required=True);p.add_argument('--archive',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(exist_ok=True,parents=True)
    result={}
    for label,path in [('live',a.live),('archive',a.archive)]:
        raw=path.read_bytes();new,changed=fix_xml(raw);count=len(ET.fromstring(raw).findall('Ad'))
        if not 150<=count<=300:raise ValueError('Unexpected catalogue size')
        (a.out/path.name).write_bytes(new)
        result[label]={'ads':count,'changed_ids':changed,'before_sha256':hashlib.sha256(raw).hexdigest(),'after_sha256':hashlib.sha256(new).hexdigest()}
    live=ET.fromstring((a.out/a.live.name).read_bytes());archive=ET.fromstring((a.out/a.archive.name).read_bytes());liveids={x.findtext('Id') for x in live};archids={x.findtext('Id') for x in archive}
    if not liveids<=archids:raise ValueError('Live IDs absent from approved archive')
    result.update(engine_type=ENGINE_TYPE,only_engine_subtype_added=True,new_ads=0,private_prices_or_credentials_written=False)
    (a.out/'avito-engine-subtype-fix-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('AVITO_ENGINE_SUBTYPE_FIX',json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
