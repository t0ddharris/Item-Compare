"""Exercise the stock Set Item / Fade In / Fade Out lifecycle from decoded bytecode.

Native asset lookup and animation playback are mocked. The cached-asset branch,
invalid-item reset, wrapper hooks, and fade requests execute the real bytecode.
Comparison eligibility is covered separately by verify_mod's comparison VM.
"""
from build_mod import SOURCE_ROOT, Asset, read


def kind(node):
    return node['$type'].split('EX_')[1].split(',')[0]


def instruction_size(node):
    """Sizes needed by the stock tooltip's item/fade entry-point region."""
    op=kind(node)
    if op in ('InstanceVariable','LocalVariable','LocalOutVariable','ObjectConst'): return 9
    if op in ('Nothing','EndOfScript','Self','True','False','NoObject','PopExecutionFlow'): return 1
    if op in ('IntConst','FloatConst','Jump','PushExecutionFlow'): return 5
    if op=='ByteConst': return 2
    if op=='NameConst': return 13
    if op=='Return': return 1+instruction_size(node['ReturnExpression'])
    if op=='Context': return 13+instruction_size(node['ObjectExpression'])+node['Offset']
    if op in ('LocalVirtualFunction','VirtualFunction'): return 14+sum(map(instruction_size,node['Parameters']))
    if op in ('FinalFunction','LocalFinalFunction','CallMath'): return 10+sum(map(instruction_size,node['Parameters']))
    if op=='Let': return 9+instruction_size(node['Variable'])+instruction_size(node['Expression'])
    if op in ('LetObj','LetBool'): return 1+instruction_size(node['VariableExpression'])+instruction_size(node['AssignmentExpression'])
    if op=='LetValueOnPersistentFrame': return 9+instruction_size(node['AssignmentExpression'])
    if op=='JumpIfNot': return 5+instruction_size(node['BooleanExpression'])
    if op=='StructConst': return 14+sum(map(instruction_size,node['Value']))
    if op=='ComputedJump': return 1+instruction_size(node['CodeOffsetExpression'])
    if op=='PopExecutionFlowIfNot': return 1+instruction_size(node['BooleanExpression'])
    if op=='BindDelegate': return 13+instruction_size(node['Delegate'])+instruction_size(node['ObjectTerm'])
    if op=='AddMulticastDelegate': return 1+instruction_size(node['Delegate'])+instruction_size(node['DelegateToAdd'])
    if op=='RemoveMulticastDelegate': return 1+instruction_size(node['Delegate'])+instruction_size(node['DelegateToAdd'])
    raise AssertionError(f'Unexpected lifecycle opcode {op}')


class NativeTooltip:
    def __init__(self,asset):
        self.asset=asset
        self.state={'Target Item Handle':None,'Target Item Asset':None,'Target Item Level':0,
                    'Fade':object(),'IC_PopupAnchor':{},'IC_ComparisonLayer':{},'Target List Item':None}
        self.frame={}
        self.fade_in=0; self.fade_out=0; self.visible=False
        self.comparison_open=False; self.allow=True; self.items={}
        self.depth=0; self.max_depth=0
        self.uber=next(e for e in asset.data['Exports'] if e['ObjectName'].startswith('ExecuteUbergraph'))
        self.uber_ops={}; address=0
        # Stop before unrelated initialization/texture-loading branches. All
        # item and fade paths used below precede that region in the stock graph.
        body=self.uber['ScriptBytecode']
        stop=next(i for i,n in enumerate(body) if n.get('VariableExpression',{}).get('Variable',{}).get('New',{}).get('Path')==['ShowUpgradePreview'])
        for node in body[:stop]:
            self.uber_ops[address]=node; address+=instruction_size(node)
        terminal=self.uber['ScriptBytecodeSize']-3
        assert kind(body[-2])=='Return' and kind(body[-1])=='EndOfScript'
        self.uber_ops[terminal]=body[-2]
        for event in ('Set Item','Fade In','Fade Out'):
            call=next(n for n in asset.export(event)['ScriptBytecode'] if kind(n)=='LocalFinalFunction')
            assert call['Parameters'][0]['Value'] in self.uber_ops,event
        self.cleanup=asset.export('IC_UpdateComparison')['ScriptBytecode'][-3]

    def function_name(self,node):
        if 'VirtualFunctionName' in node: return node['VirtualFunctionName']
        index=node['StackNode']
        return (self.asset.data['Exports'][index-1] if index>0 else self.asset.data['Imports'][-index-1])['ObjectName']

    def invoke(self,name,args=()):
        self.depth+=1; self.max_depth=max(self.max_depth,self.depth)
        assert self.depth<8,'Recursive cleanup did not terminate'
        try:
            if name=='IC_UpdateComparison':
                # Choose the lifecycle path using the scenario's source state;
                # the separate comparison VM checks the serialized guards.
                self.comparison_open=False
                handle=self.state['Target Item Handle']
                if handle is None or not self.allow: return
                if self.items.get(handle,0)>0:
                    self.comparison_open=True
                else:
                    self.evaluate(self.cleanup,{})
                return
            if name=='Update Item Display': return
            export=self.asset.export(name)
            if name==self.uber['ObjectName']:
                self.frame['EntryPoint']=args[0]
                return self.execute(self.uber_ops,self.frame)
            params=[p['Name'] for p in export['LoadedProperties']
                    if 'CPF_Parm' in p['PropertyFlags'] and 'CPF_ReturnParm' not in p['PropertyFlags']]
            if name=='Set Item' and len(params)==4 and len(args)==3:
                args=[*args,None]  # 1.1's added optional source-list widget.
            assert len(params)==len(args),(name,params,args)
            local=dict(zip(params,args))
            ops={}; address=0
            for node in export['ScriptBytecode']:
                ops[address]=node; address+=instruction_size(node)
            assert address==export['ScriptBytecodeSize'],name
            return self.execute(ops,local)
        finally:
            self.depth-=1

    def execute(self,ops,local):
        pc=0; flow=[]; steps=0
        while True:
            steps+=1; assert steps<100,'Stock lifecycle did not terminate'
            node=ops[pc]; op=kind(node)
            if op=='Return': return
            if op=='PushExecutionFlow': flow.append(node['PushingAddress'])
            elif op=='ComputedJump': pc=self.evaluate(node['CodeOffsetExpression'],local); continue
            elif op=='Jump': pc=node['CodeOffset']; continue
            elif op=='JumpIfNot' and not self.evaluate(node['BooleanExpression'],local):
                pc=node['CodeOffset']; continue
            elif op=='PopExecutionFlow' or (op=='PopExecutionFlowIfNot' and not self.evaluate(node['BooleanExpression'],local)):
                pc=flow.pop(); continue
            elif op not in ('JumpIfNot','PopExecutionFlowIfNot'):
                self.evaluate(node,local)
            pc+=instruction_size(node)

    def assign(self,node,value,local,context=None):
        op=kind(node)
        if op=='Context':
            return self.assign(node['ContextExpression'],value,local,self.evaluate(node['ObjectExpression'],local))
        dest=local if op in ('LocalVariable','LocalOutVariable') else (self.state if context is None else context)
        dest[node['Variable']['New']['Path'][0]]=value

    def evaluate(self,node,local,context=None):
        op=kind(node)
        if op in ('True','False'): return op=='True'
        if op in ('Nothing','NoObject'): return None
        if op=='Self': return self.state
        if op=='ObjectConst': return {'object':node['Value']}
        if op in ('IntConst','ByteConst','FloatConst'): return node['Value']
        if op=='StructConst':
            assert self.asset.data['Imports'][-node['Struct']-1]['ObjectName']=='ItemHandle' and node['Value']==[]
            return None
        if op in ('InstanceVariable','LocalVariable','LocalOutVariable'):
            dest=local if op in ('LocalVariable','LocalOutVariable') else (self.state if context is None else context)
            return dest[node['Variable']['New']['Path'][0]]
        if op=='Context': return self.evaluate(node['ContextExpression'],local,self.evaluate(node['ObjectExpression'],local))
        if op=='Let': return self.assign(node['Variable'],self.evaluate(node['Expression'],local),local)
        if op in ('LetObj','LetBool'): return self.assign(node['VariableExpression'],self.evaluate(node['AssignmentExpression'],local),local)
        if op=='LetValueOnPersistentFrame':
            self.frame[node['DestinationProperty']['New']['Path'][0]]=self.evaluate(node['AssignmentExpression'],local); return
        if op in ('FinalFunction','LocalFinalFunction','CallMath','LocalVirtualFunction','VirtualFunction'):
            name=self.function_name(node); params=node['Parameters']
            if name=='GetAssetForItem':
                handle=self.evaluate(params[0],local)
                self.assign(params[1],1 if handle else 0,local)
                return handle  # All non-null scenario handles remain globally valid.
            args=[self.evaluate(p,local) for p in params]
            if name=='GetGameInstanceSubsystem': return {'subsystem':True}
            if name=='Max': return max(args)
            if name=='IsValid': return args[0] is not None
            if name=='EqualEqual_ObjectObject': return args[0] is args[1]
            if name=='DeregisterInputProcessor': return
            if name=='SetVisibility': context['visibility']=args[0]; return
            if name=='Close': context['open']=False; self.comparison_open=False; return
            if name=='PlayAnimationForward': self.fade_in+=1; self.visible=True; return object()
            if name=='PlayAnimationReverse': self.fade_out+=1; self.visible=False; return object()
            if name=='SetRenderOpacity': self.visible=float(args[0])>0; return
            return self.invoke(name,args)
        raise AssertionError(op)


def verify_lifecycle(current):
    baseline_path=SOURCE_ROOT/'history/v1.1.0-before-purchase-fix/WBP_IC_TradeStorageTooltip.json'
    reproduced=False
    if baseline_path.is_file():
        baseline=Asset(read(baseline_path))
        old=NativeTooltip(baseline)
        old.items={'bought sword':1,'next sword':1}
        old.invoke('Set Item',['bought sword',1,False])
        assert old.visible and old.fade_in==1
        old.items.pop('bought sword')
        old.invoke('IC_UpdateComparison')
        assert not old.visible and old.state['Target Item Asset'] is not None
        old.invoke('Set Item',['next sword',1,False])
        assert not old.visible and old.fade_in==1,'The v1.1.0 regression was not reproduced'
        reproduced=True

    cases=0
    for destination,allowed in [('merchant',True),('character',False),('storage',True)]:
        card=NativeTooltip(current)
        card.items={'bought sword':1,'next sword':1}
        card.invoke('Set Item',['bought sword',1,False])
        assert card.visible and card.comparison_open
        card.items.pop('bought sword')
        card.invoke('IC_UpdateComparison')  # Inventory notification, no hover.
        assert not card.visible and not card.comparison_open
        assert card.state['Target Item Asset'] is None and card.state['Target Item Handle'] is None
        previous_fades=card.fade_out
        card.invoke('IC_UpdateComparison')
        assert card.fade_out==previous_fades,'Repeated notification restarted the fade'
        card.allow=allowed
        card.invoke('Set Item',['next sword',1,False])
        assert card.visible and card.fade_in==2,destination
        assert card.comparison_open==allowed
        card.invoke('SetComparedItemSlot',[0])
        assert card.visible and card.comparison_open==allowed
        assert card.max_depth<8
        cases+=1
    card=NativeTooltip(current); card.items={'ring':3,'other ring':1}
    card.invoke('Set Item',['ring',3,False])
    for remaining in (2,2,1):  # Partial, failed, and another partial transaction.
        card.items['ring']=remaining
        card.invoke('IC_UpdateComparison')
        assert card.visible and card.fade_out==0 and card.fade_in==1
        cases+=1
    card.items.pop('ring'); card.invoke('IC_UpdateComparison')
    card.invoke('Set Item',['other ring',1,False])
    assert card.visible and card.comparison_open and card.fade_in==2
    cases+=1
    # Repeated purchases without closing/recreating the shop widget.
    for index in range(3):
        handle=f'purchase {index}'
        card.items[handle]=1
        card.invoke('Set Item',[handle,1,False])
        assert card.visible and card.comparison_open
        card.items.pop(handle); card.invoke('IC_UpdateComparison')
        card.invoke('Set Item',['other ring',1,False])
        assert card.visible and card.comparison_open
        cases+=1
    return {'v1_1_0_regression_reproduced':reproduced,'recovery_cases':cases}
