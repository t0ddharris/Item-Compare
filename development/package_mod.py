"""Package verified mod files with the user's public documents verbatim."""
import hashlib
import argparse
import zipfile

from build_mod import ROOT, VERSION, STEM, VARIANTS, release_paths, read, write


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant',choices=VARIANTS,default='default')
    args=parser.parse_args()
    work,dist=release_paths(args.variant)
    report=read(work/'verification-report.json')
    assert report['status']=='static checks passed'
    assert report['version']==VERSION,'Validation report belongs to another release'
    assert report.get('variant','default')==args.variant,'Validation report belongs to another variant'
    payload_names=[STEM+s for s in ('.pak','.ucas','.utoc')]
    assert set(report['payloads'])==set(payload_names)
    for name in ('README.txt','CHANGELOG.txt'):
        assert (dist/name).is_file(),f'Prepare the public {name} in {dist} before packaging'
    names=['README.txt','CHANGELOG.txt']+payload_names
    # These documents are editable source files, not generated build output.
    # Snapshot their bytes along with the payload; never replace user edits.
    contents={name:(dist/name).read_bytes() for name in names}
    hashes={name:hashlib.sha256(data).hexdigest() for name,data in contents.items()}
    for name in payload_names: assert hashes[name]==report['payloads'][name],name
    archive=dist.parent/(dist.name+'.zip')
    manifest_path=archive.with_suffix('.manifest.json')
    previous=read(manifest_path) if manifest_path.exists() else {}
    pending=archive.with_suffix('.zip.tmp')
    with zipfile.ZipFile(pending,'w',zipfile.ZIP_DEFLATED) as z:
        for name in names: z.writestr(name,contents[name])
    with zipfile.ZipFile(pending) as z:
        assert set(z.namelist())==set(names)
        assert z.testzip() is None
        for name in names:
            assert z.read(name)==contents[name]
            assert (dist/name).read_bytes()==contents[name],f'{name} changed during packaging; rerun'
    pending.replace(archive)
    checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{checksum}  {archive.name}\n',encoding='ascii')
    manifest={'version':VERSION,'variant':args.variant,'game_version':report.get('game_version'),'archive':archive.name,'archive_bytes':archive.stat().st_size,
        'archive_sha256':checksum,
        'contents':[{'name':name,'bytes':len(contents[name]),'sha256':hashes[name]} for name in names],
        'assets':[p.replace('\\','/') for p in report['verified_assets']],
        'automated_verification':{k:report[k] for k in ('status','control_flow_cases',
            'layout_contract_cases','inventory_boundary_cases','shop_storage_control_flow_cases',
            'shop_storage_layout_cases','shop_storage_position_cases','shop_storage_source_filter_cases',
            'shop_storage_transfer_cases','tooltip_lifecycle_recovery_cases','v1_1_0_regression_reproduced',
            'heading_localization_cases','stock_widget_preservation_cases','shared_scroll_cases',
            'checks','game_runtime_verified')}}
    # Documentation changes do not invalidate prior acceptance of identical
    # mod bytes. Never carry acceptance forward after a payload change.
    old_payloads={item['name']:item['sha256'] for item in previous.get('contents',[])
                  if item['name'] in payload_names}
    if old_payloads==report['payloads'] and 'user_acceptance' in previous:
        manifest['user_acceptance']=previous['user_acceptance']
    write(manifest_path,manifest)
    print(f'{archive}\nSHA-256: {checksum}')


if __name__=='__main__': main()
