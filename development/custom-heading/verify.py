"""Run the actual companion Lua under Lua 5.4 with mocked UE4SS boundaries."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'development/tools/lua-test-runtime'))
from lupa.lua54 import LuaRuntime


def verify(scripts=None):
    scripts = scripts or ROOT/'addons/ItemCompareCustomHeading/Scripts'
    runtime = LuaRuntime(unpack_returned_tuples=True)
    main = (scripts/'main.lua').read_text(encoding='utf-8')
    config = (scripts/'config.lua').read_text(encoding='utf-8')
    harness = Path(__file__).with_name('test_runtime.lua').read_text(encoding='utf-8')
    count = runtime.execute(harness, main, config)
    return {'addon_version': '1.0.1', 'status': 'Lua checks passed',
            'runtime': runtime.lua_implementation, 'cases': count,
            'ue4ss_calls': 'mocked', 'game_runtime_verified': False,
            'scripts': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in (scripts/'main.lua', scripts/'config.lua')}}


if __name__ == '__main__':
    report = verify()
    Path(__file__).with_name('verification-report.json').write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
