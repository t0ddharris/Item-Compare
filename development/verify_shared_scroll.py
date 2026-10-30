"""Execute scroll forwarding and stock offset arithmetic; native input is mocked."""
import copy
from build_mod import Asset, ROOT, read, size, walk


def verify_shared_scroll(asset):
    stock=Asset(read(ROOT/'decoded/tooltip.json'))
    original=stock.export('OnScrolled')
    event=asset.export('OnScrolled')
    assert event['LoadedProperties']==original['LoadedProperties']
    assert event['ScriptBytecode'][:2]==original['ScriptBytecode'][:2]
    graph=next(e for e in stock.data['Exports'] if e['ObjectName'].startswith('ExecuteUbergraph'))
    body=graph['ScriptBytecode']
    start=next(i for i,n in enumerate(body) if any(v.get('Path')==['K2Node_Event_Value'] for v in walk(n)))
    end=next(i for i in range(start,len(body)) if 'EX_PopExecutionFlow,' in body[i]['$type'])
    stock_scroll=body[start:end]
    assert not any(n.get('StackNode') in (asset.imp('RegisterInputProcessor'),asset.imp('DeregisterInputProcessor'))
                   for n in walk(event['ScriptBytecode']))

    def run(wrapper,opened,shown,delta,offsets,limits):
        cards=[{'StatsScrollBox':{'offset':x,'end':y}} for x,y in zip(offsets,limits)]
        main=cards[0]
        main.update(IC_PopupAnchor={'open':opened})
        for i in range(2):
            main[f'IC_Group{i}']={'visibility':3 if shown[i] else 1}
            main[f'IC_EquippedTooltip{i}']=cards[i+1]
        calls=[]
        def evaluate(n,context,local):
            kind=n['$type'].split('EX_')[1].split(',')[0]
            if kind.endswith('Const'): return float(n['Value'])
            if kind in ('LocalVariable','InstanceVariable'):
                return (local if kind=='LocalVariable' else context)[n['Variable']['New']['Path'][0]]
            if kind=='Context': return evaluate(n['ContextExpression'],evaluate(n['ObjectExpression'],context,local),local)
            if kind=='PrimitiveCast': return evaluate(n['Target'],context,local)
            if kind=='Let':
                local[n['Variable']['Variable']['New']['Path'][0]]=evaluate(n['Expression'],context,local); return
            if kind=='LetValueOnPersistentFrame':
                local[n['DestinationProperty']['New']['Path'][0]]=evaluate(n['AssignmentExpression'],context,local); return
            if kind=='LocalFinalFunction':
                assert n==original['ScriptBytecode'][1]
                for op in stock_scroll: evaluate(op,main,local)
                return
            if kind in ('FinalFunction','LocalVirtualFunction','CallMath'):
                name=n.get('VirtualFunctionName') or asset.data['Imports'][-n['StackNode']-1]['ObjectName']
                args=[evaluate(p,context,local) for p in n['Parameters']]
                if name=='IsOpen': return context['open']
                if name=='GetVisibility': return context['visibility']
                if name=='EqualEqual_ByteByte': return args[0]==args[1]
                if name=='OnScrolled':
                    calls.append((next(i for i,c in enumerate(cards) if c is context),args[0]))
                    child_local={'K2Node_Event_Value':args[0]}
                    for op in stock_scroll: evaluate(op,context,child_local)
                    return
                if name=='GetScrollOffset': return context['offset']
                if name=='GetScrollOffsetOfEnd': return context['end']
                if name=='SetScrollOffset': context['offset']=args[0]; return
                if name=='Multiply_DoubleDouble': return args[0]*args[1]
                if name=='Add_DoubleDouble': return args[0]+args[1]
                if name=='FClamp': return max(args[1],min(args[0],args[2]))
                raise AssertionError(name)
            raise AssertionError(kind)
        ops={}; address=0
        for n in wrapper:
            ops[address]=n; address+=size(n)
        pc=0; local={'Value':delta}
        for _ in range(30):
            n=ops[pc]; kind=n['$type'].split('EX_')[1].split(',')[0]
            if kind=='Return': break
            if kind=='JumpIfNot':
                if not evaluate(n['BooleanExpression'],main,local): pc=n['CodeOffset']; continue
            else: evaluate(n,main,local)
            pc+=size(n)
        else: raise AssertionError('Scroll forwarding did not terminate')
        expected=[(i+1,delta) for i in range(2) if opened and shown[i]]
        assert calls==expected, 'Missing or unexpected comparison scroll'
        for i,c in enumerate(cards):
            wanted=max(0,min(limits[i],offsets[i]-100*delta)) if i==0 or (i,delta) in expected else offsets[i]
            assert abs(c['StatsScrollBox']['offset']-wanted)<1e-6

    cases=0
    # Whole wheel steps and fractional analog-stick deltas; short main card,
    # differing card lengths, independent end stops, empty slots, closed popup.
    for opened,shown in ((True,(True,True)),(True,(True,False)),(True,(False,True)),
                         (True,(False,False)),(False,(True,True))):
        for delta in (-1,1,-0.15,0.15,0,8,-8):
            for offsets,limits in (((0,0,0),(0,900,250)),((100,250,20),(100,900,20))):
                run(event['ScriptBytecode'],opened,shown,delta,offsets,limits); cases+=1
    # The previous wrapper scrolls the main card only; the check must reject it.
    try: run(copy.deepcopy(original['ScriptBytecode']),True,(True,True),-1,(0,0,0),(0,900,250))
    except AssertionError as error: assert str(error)=='Missing or unexpected comparison scroll'
    else: raise AssertionError('Main-only scrolling regression was not detected')
    return cases
