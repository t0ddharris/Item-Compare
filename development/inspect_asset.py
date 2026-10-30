import json, sys
from pathlib import Path

a = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
def name(i):
    if not i: return 'null'
    return (a['Exports'][i-1] if i > 0 else a['Imports'][-i-1])['ObjectName']
def compact(v):
    if isinstance(v, list): return [compact(x) for x in v]
    if not isinstance(v, dict): return v
    if 'New' in v: return f"{name(v['New']['ResolvedOwner'])}.{'.'.join(v['New']['Path'])}"
    r = {}
    for k,x in v.items():
        if k == '$type': r['op'] = x.split(',')[0].split('.')[-1]
        elif k in ('StackNode','ClassPtr','Struct'): r[k] = name(x)
        else: r[k] = compact(x)
    return r
if len(sys.argv) < 3:
    for i,e in enumerate(a['Exports']):
        print(i+1, e['ObjectName'], ', '.join(x.get('Name','?') for x in e.get('LoadedProperties',[])))
else:
    for e in a['Exports']:
        if e['ObjectName'] in sys.argv[2:]:
            print(e['ObjectName'])
            if 'ScriptBytecode' in e:
                for x in e['ScriptBytecode'] or []: print(json.dumps(compact(x)))
            else: print(json.dumps(e, indent=2))
