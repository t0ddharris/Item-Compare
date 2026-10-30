"""Import the pristine 1.1 extraction retained by the Better Quickslots audit.

Copies references; never writes to the other mod or the installed game.
"""
from pathlib import Path
import hashlib
import shutil
import argparse
from build_mod import ROOT, SOURCE_ROOT, MAPPING, read, run, write

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--mapping',type=Path,required=True,help='Fresh .usmap dumped from Dawnwalker 1.1')
parser.add_argument('--reuse-extraction',action='store_true')
parser.add_argument('--extracted-root',type=Path,help='Pristine extracted tree containing Dawnwalker/Content')
parser.add_argument('--game-paks',type=Path,default=Path('D:/Steam/steamapps/common/The Blood of Dawnwalker/Dawnwalker/Content/Paks'))
args=parser.parse_args()
assert args.mapping.is_file(), args.mapping
mapping_target=SOURCE_ROOT/'tools/Data/Mappings'/(MAPPING+'.usmap')
mapping_target.parent.mkdir(parents=True,exist_ok=True)
shutil.copy2(args.mapping,mapping_target)

stock = SOURCE_ROOT.parent.parent / 'better-quickslots-dawnwalker/development/patch11-stock'
game = args.game_paks
extracted = args.extracted_root or stock / 'extracted'
assert extracted.is_dir() or args.reuse_extraction, extracted
for suffix in (() if args.extracted_root or args.reuse_extraction else ('.utoc', '.ucas')):
    current = (game / ('global' + suffix)).read_bytes()
    assert current == (stock / 'verify-v02-containers' / ('global' + suffix)).read_bytes()
ROOT.mkdir(exist_ok=True)
for source in extracted.rglob('*'):
    if args.reuse_extraction: break
    if source.suffix not in ('.uasset', '.uexp', '.ubulk'): continue
    target = ROOT / 'extracted' / source.relative_to(extracted)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
ui = 'Dawnwalker/Content/_Dawnwalker/UI/_Unified/'
inputs = {
    'tooltip': 'GameHub/Inventory/Tooltip/WBP_Inventory_ItemTooltip',
    'panel': 'GameHub/Inventory/WBP_InventoryPanel',
    'double-inventory': 'ShopAndStorage/WBP_DoubleInventoryBase',
    'shop': 'ShopAndStorage/Shop/WBP_Shop_New',
    'storage': 'ShopAndStorage/Storage/WBP_Storage_New',
}
(ROOT / 'decoded').mkdir(exist_ok=True)
for name, rel in inputs.items():
    source = ROOT / 'extracted' / (ui + rel + '.uasset')
    assert source.exists(), source
    output = ROOT / 'decoded' / (name + '.json')
    output.unlink(missing_ok=True)
    run(SOURCE_ROOT / 'tools/UAssetGUI.exe', 'tojson', source, output, 'VER_UE5_5', MAPPING)
    data = read(output)
    assert not any('RawExport' in e['$type'] for e in data['Exports']), name
    print(name, len(data['Exports']), flush=True)
write(ROOT / 'input-provenance.json', {
    'game_version': '1.1', 'source': str(ROOT / 'extracted' if args.reuse_extraction else extracted),
    'global_ucas_sha256': hashlib.sha256((game / 'global.ucas').read_bytes()).hexdigest(),
    'mapping_sha256': hashlib.sha256(mapping_target.read_bytes()).hexdigest(),
    'inputs': {name: hashlib.sha256((ROOT / 'decoded' / (name + '.json')).read_bytes()).hexdigest() for name in inputs},
})
