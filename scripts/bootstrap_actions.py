"""Verify a migration export and publish only its encrypted runtime snapshot."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pm_scraper.actions_runner import key_bytes, persist, unseal


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--bundle-dir',type=Path,required=True)
    p.add_argument('--state-checkout',type=Path,required=True)
    p.add_argument('--key-file',type=Path,required=True)
    p.add_argument('--refresh',action='store_true',help='Replace the snapshot after obtaining a fresh migration export; history remains intact')
    args=p.parse_args()
    raw=(args.bundle_dir/'MANIFEST.json').read_text()
    manifest,end=json.JSONDecoder().raw_decode(raw)
    if raw[end:].strip() not in ('','\\n'):
        raise ValueError('Unexpected data after migration manifest')
    expected={'ACTIVE_TASK.json','PM_Career_Scraper_State.sqlite3','PM_Career_Scraper_Report.md'}
    if {f['name'] for f in manifest['files']} != expected or len(manifest['files']) != 3:
        raise ValueError('Unexpected migration manifest payload')
    for entry in manifest['files']:
        b=(args.bundle_dir/entry['name']).read_bytes()
        if len(b)!=entry['size_bytes'] or hashlib.sha256(b).hexdigest()!=entry['sha256']:
            raise ValueError('Migration payload hash mismatch')
    task=json.loads((args.bundle_dir/'ACTIVE_TASK.json').read_text())
    recipients=set(re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',task['prompt']))
    if len(recipients)!=1:
        raise ValueError('Expected one unambiguous task recipient')
    existing=(args.state_checkout/'state.enc').exists()
    if existing and (not args.refresh or not args.key_file.exists()):
        raise ValueError('Existing encrypted state requires --refresh and the original key')
    if not args.key_file.exists():
        args.key_file.parent.mkdir(parents=True,exist_ok=True)
        with args.key_file.open('x') as keyfile:
            keyfile.write(base64.b64encode(os.urandom(32)).decode()+'\n')
        args.key_file.chmod(0o600)
    key=key_bytes(args.key_file.read_text())
    with tempfile.TemporaryDirectory(prefix='tiny-bootstrap-') as temp:
        folder=Path(temp)
        if existing:
            # A wrong refresh key must fail before making any commit.
            unseal((args.state_checkout/'state.enc').read_bytes(),folder,key)
            old_meta=json.loads((folder/'meta.json').read_text())
            if any(a.get('status') in {'sending','prepared'} for a in old_meta.get('attempts',{}).values()):
                raise ValueError('Resolve outstanding delivery before refreshing state')
        else:
            old_meta={}
        shutil.copyfile(args.bundle_dir/'PM_Career_Scraper_State.sqlite3',folder/'state.sqlite3')
        shutil.copyfile(args.bundle_dir/'PM_Career_Scraper_Report.md',folder/'audit.md')
        meta={'recipient':next(iter(recipients)), 'attempts':old_meta.get('attempts',{}),
              'imported_database_sha256':hashlib.sha256((folder/'state.sqlite3').read_bytes()).hexdigest()}
        (folder/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
        persist(folder,args.state_checkout,key,'Import verified migration snapshot')
    print('Encrypted runtime state published; the key was retained in the requested local file. No readable runtime data was committed.')


if __name__=='__main__':
    main()
