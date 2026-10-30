"""Verify the packaged mod by resolving imports and decoding its actual payload."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from build_mod import (ROOT, SOURCE_ROOT, MAPPING, UI, PRIVATE, ORIGINAL, STEM, VERSION, Asset, getprop,
                       read, run, size, walk, write, rename)
from storage_mod import STORAGE_PRIVATE, STORAGE_ASSETS
from verify_tooltip_lifecycle import verify_lifecycle
from verify_localization import verify_localization
from verify_shared_scroll import verify_shared_scroll
from build_mod import VARIANTS, release_paths


def normalized(v):
    if isinstance(v, dict): return {k:normalized(x) for k,x in v.items() if k!='IsZero'}
    if isinstance(v, list):
        values=[normalized(x) for x in v]
        if values and all(isinstance(x,dict) and 'Name' in x for x in values):
            values.sort(key=lambda x:x['Name'])
        return values
    if v in ('+0','-0'): return 0.0
    return round(v,6) if isinstance(v,float) else v


def verify_patch11_stock_widgets(primary, secondary):
    """Preserve 1.1's scrolling subtree and the button named in the crash."""
    original=Asset(read(ROOT/'decoded/tooltip.json'))
    def button_header(asset,path):
        entry=asset.export('EquipButton')
        data=path.read_bytes()+path.with_suffix('.uexp').read_bytes()
        start=entry['SerialOffset']; end=start
        while True:
            fragment=int.from_bytes(data[end:end+2],'little'); end+=2
            if fragment & 0x100: return data[start:end]
            assert end-start<entry['SerialSize']
    stock_header=button_header(original,ROOT/'extracted'/UI/'Tooltip'/f'{ORIGINAL}.uasset')
    count=0
    for before,after in zip(original.data['Exports'],primary.data['Exports']):
        assert before['ObjectName'].replace(ORIGINAL,PRIVATE)==after['ObjectName']
        if 'NormalExport' not in before['$type']: continue
        ignored={'Slot'} if before['ObjectName']=='VerticalBox_0' else set()
        if before['ObjectName']=='WidgetTree': ignored={'RootWidget'}
        assert normalized(rename([p for p in before['Data'] if p['Name'] not in ignored],ORIGINAL,PRIVATE))==normalized(
            [p for p in after['Data'] if p['Name'] not in ignored]),('1.1 stock widget',before['ObjectName'])
        count+=1
    for tooltip in (primary,secondary):
        name=PRIVATE if tooltip is primary else STORAGE_PRIVATE
        assert button_header(tooltip,ROOT/'verified'/UI/'Tooltip'/f'{name}.uasset')==stock_header
        button=tooltip.export('EquipButton')
        stock_button=original.export('EquipButton')
        assert normalized(button['Data'])==normalized(stock_button['Data'])
        assert button['SerialSize']==stock_button['SerialSize']
        assert button['Extras']==stock_button['Extras']==''
        assert [p['Name'] for p in tooltip.export('Set Item')['LoadedProperties']
                if 'CPF_Parm' in p['PropertyFlags']]==['Item Handle','Stack Size','Equippable','ListItem']
        calls=[n for n in walk(tooltip.export('IC_UpdateComparison')['ScriptBytecode'])
               if n.get('VirtualFunctionName')=='Set Item']
        assert len(calls)==(2 if tooltip is primary else 3)
        for call in calls:
            assert len(call['Parameters'])==4
            assert 'EX_NoObject,' in call['Parameters'][3]['$type']
    return count


def verify_behavior(a,source_screen=None,details=None):
    """Execute the packaged control flow with mocked read-only game calls.

    This checks stale-state cleanup, branch offsets, array bounds, correct item
    handles, independent empty slots, and both rings. It is not a game UI test.
    """
    fn=a.export('IC_UpdateComparison')
    instructions=fn['ScriptBytecode']
    address=0; ops={}
    for op in instructions:
        ops[address]=op; address+=size(op)
    assert address==fn['ScriptBytecodeSize']
    for node in walk(instructions):
        if 'EX_JumpIfNot,' in node.get('$type',''): assert node['CodeOffset'] in ops
        if 'EX_Context,' in node.get('$type',''): assert node['Offset']==size(node['ContextExpression'])

    class VM:
        def __init__(self):
            self.widgets={n:{} for n in ('IC_ComparisonLayer','IC_PopupAnchor','IC_Group0','IC_Group1',
                                         'IC_EquippedTooltip0','IC_EquippedTooltip1')}
            self.self_={**self.widgets,'Target Item Handle':None}
            self.self_['input_registered']=True
        def run(self,handle,slots,equipment,other_loadout=(),allow_comparison=True,source_quantity=1):
            self.self_['Target Item Handle']=handle
            self.self_['IC_AllowComparison']=allow_comparison
            self.self_['IC_SourceInventory']=None if source_quantity is None else {'items':{handle:source_quantity}}
            self.slots=slots; self.equipment=equipment
            self.equipped=set(equipment.values())|set(other_loadout)
            return self.refresh()
        def refresh(self):
            self.locals={}; self.shown=[]
            self.equipment_reads=0; self.source_reads=0; self.fade_requested=False
            pc=0; steps=0
            while True:
                op=ops[pc]; kind=op['$type'].split('EX_')[1].split(',')[0]
                steps+=1; assert steps<100
                if kind=='Return': break
                if kind=='JumpIfNot' and not self.eval(op['BooleanExpression']):
                    pc=op['CodeOffset']; continue
                if kind!='JumpIfNot': self.eval(op)
                pc+=size(op)
            self.check_input_ownership()
            return [(i,self.widgets[f'IC_EquippedTooltip{i}']['item']) for i in range(2)
                    if self.widgets[f'IC_Group{i}'].get('visibility')==3]
        def check_input_ownership(self):
            assert self.self_['input_registered'], 'Primary tooltip lost scrolling input'
            assert not any(self.widgets[f'IC_EquippedTooltip{i}'].get('input_registered',False)
                           for i in range(2)), 'Passive comparison retained scroll input'
        def assign(self,node,value,context=None):
            kind=node['$type'].split('EX_')[1].split(',')[0]
            if kind=='Context': return self.assign(node['ContextExpression'],value,self.eval(node['ObjectExpression']))
            assert kind in ('LocalVariable','InstanceVariable')
            dest=self.locals if kind=='LocalVariable' else (self.self_ if context is None else context)
            dest[node['Variable']['New']['Path'][0]]=value
        def eval(self,node,context=None):
            if 'EX_NoObject,' in node['$type']: return None
            kind=node['$type'].split('EX_')[1].split(',')[0]
            if kind in ('IntConst','ByteConst'): return node['Value']
            if kind in ('True','False'): return kind=='True'
            if kind=='Self': return self.self_
            if kind=='ObjectConst': return {'library':node['Value']}
            if kind=='StructConst':
                assert a.data['Imports'][-node['Struct']-1]['ObjectName']=='ItemHandle'
                assert node['StructSize']==4 and node['Value']==[]
                return None
            if kind in ('LocalVariable','InstanceVariable'):
                dest=self.locals if kind=='LocalVariable' else (self.self_ if context is None else context)
                return dest[node['Variable']['New']['Path'][0]]
            if kind=='Context': return self.eval(node['ContextExpression'],self.eval(node['ObjectExpression']))
            if kind=='Let': return self.assign(node['Variable'],self.eval(node['Expression']))
            if kind=='LetBool': return self.assign(node['VariableExpression'],self.eval(node['AssignmentExpression']))
            if kind in ('LocalVirtualFunction','FinalFunction','CallMath'):
                name=node.get('VirtualFunctionName') or a.data['Imports'][-node['StackNode']-1]['ObjectName']
                params=node['Parameters']
                if name=='Array_Get':
                    arr=self.eval(params[0]); idx=self.eval(params[1]); assert 0<=idx<len(arr)
                    return self.assign(params[2],arr[idx])
                args=[self.eval(p) for p in params]
                if name=='IsValid': return args[-1] is not None
                if name=='Get User Inventory Component': return {'inventory':True}
                if name=='Is Item Equipped':
                    assert args[2:4]==[-1,True]
                    assert args[4] is self.self_
                    return args[1] in self.equipped
                if name=='Not_PreBool': return not args[0]
                if name=='GetValidSlotsForCurrentItem': return self.slots
                if name=='Greater_IntInt': return args[0]>args[1]
                if name=='Array_Length': return len(args[0])
                if name=='GetEquippedItem':
                    assert args[1:]==[-1,True]  # Same lookup convention as stock UI.
                    self.equipment_reads+=1
                    return self.equipment.get(args[0])
                if name=='GetItemQuantity':
                    assert context is self.self_['IC_SourceInventory']
                    assert len(args)==2 and args[1] is False
                    self.source_reads+=1
                    return context['items'].get(args[0],0)
                if name=='Fade Out':
                    assert not args
                    for op in a.export('Fade Out')['ScriptBytecode'][:2]: self.eval(op)
                    # The remaining unchanged stock wrapper requests the main
                    # card's fade animation; no rendered animation is mocked.
                    self.fade_requested=True; return
                if name=='SetVisibility': context['visibility']=args[0]; return
                if name in ('RegisterInputProcessor','DeregisterInputProcessor'):
                    assert context is not None and not args
                    context['input_registered']=name=='RegisterInputProcessor'; return
                if name=='Close':
                    assert context is self.widgets['IC_PopupAnchor'] and args==[]
                    context['open']=False; return
                if name=='Open':
                    self.check_input_ownership()
                    assert context is self.widgets['IC_PopupAnchor'] and args==[False]
                    assert self.shown,'Popup opened without comparison content'
                    assert self.widgets['IC_ComparisonLayer']['visibility']==3
                    # Both cards must be populated before the popup measures.
                    assert len(self.shown)==sum(self.widgets[f'IC_Group{i}']['visibility']==3 for i in range(2))
                    context['open']=True; return
                if name=='Set Item':
                    if context is None:
                        assert args==[None,0,False,None]
                        # Only the native reset's effects are mocked here.
                        # verify_lifecycle executes the real Set Item/fade
                        # bytecode and checks subsequent hover recovery.
                        for op in a.export('Fade Out')['ScriptBytecode'][:2]: self.eval(op)
                        self.self_.update({'Target Item Handle':None,'Target Item Asset':None,'Target Item Level':0})
                        self.fade_requested=True; return
                    assert args[1:]==[1,False,None]
                    context['input_registered']=True  # Stock Update Item Display registration.
                    context['item']=args[0]; self.shown.append(args[0]); return
                raise AssertionError(f'Unexpected game call: {name}')
            raise AssertionError(kind)

    vm=VM()
    cases=[
        ('weapon',['sword'],{'sword':'equipped sword'},[(0,'equipped sword')]),
        ('clothing',['chest'],{'chest':'equipped shirt'},[(0,'equipped shirt')]),
        ('amulet',['amulet'],{'amulet':'equipped pendant'},[(0,'equipped pendant')]),
        ('ring',['ring1','ring2'],{'ring1':'ruby','ring2':'emerald'},[(0,'ruby'),(1,'emerald')]),
        ('emerald',['ring1','ring2'],{'ring1':'ruby','ring2':'emerald'},[]),
        ('ring',['ring1','ring2'],{'ring1':'ruby','ring2':'emerald'},[(0,'ruby'),(1,'emerald')]),
        ('ruby',['ring1','ring2'],{'ring1':'ruby','ring2':'emerald'},[]),
        ('ring',['ring1','ring2'],{'ring2':'emerald'},[(1,'emerald')]),
        ('ring',['ring1','ring2'],{'ring1':'ruby'},[(0,'ruby')]),
        ('ring',['ring1','ring2'],{},[]),
        ('food',[],{},[]),('material',[],{},[]),('quest item',[],{},[]),
        (None,[],{},[]),
        ('ring',['ring1','ring2'],{'ring1':'new ruby','ring2':'new emerald'},[(0,'new ruby'),(1,'new emerald')]),
        ('weapon',['sword'],{},[]),
        ('equipped sword',['sword'],{'sword':'equipped sword'},[]),
        ('equipped shirt',['chest'],{'chest':'equipped shirt'},[]),
        ('equipped pendant',['amulet'],{'amulet':'equipped pendant'},[]),
        # Same target across unequip/equip transitions while inventory is open.
        ('ruby',['ring1','ring2'],{'ring2':'emerald'},[(1,'emerald')]),
        ('ruby',['ring1','ring2'],{'ring1':'ruby','ring2':'emerald'},[]),
        ('ruby',['ring1','ring2'],{'ring2':'emerald'},[(1,'emerald')]),
    ]
    for item,slots,equipment,expected in cases:
        assert vm.run(item,slots,equipment)==expected,item
        assert vm.widgets['IC_ComparisonLayer']['visibility']==(3 if expected else 1),item
        assert vm.widgets['IC_PopupAnchor']['open']==bool(expected),item
        for i,_ in expected: assert vm.widgets[f'IC_EquippedTooltip{i}']['IntemSlotComparedTo']==i
        if item in equipment.values():
            assert vm.equipment_reads==0 and not vm.shown,'Equipped hover reached the rendering path'
    # The stock predicate searches both loadouts; suppress an item equipped in
    # the alternate set too, even if it is not the item returned for comparison.
    assert vm.run('night sword',['sword'],{'sword':'day sword'},['night sword'])==[]
    assert vm.widgets['IC_ComparisonLayer']['visibility']==1 and vm.equipment_reads==0
    assert not vm.widgets['IC_PopupAnchor']['open']
    source_cases=0; transfer_cases=0
    if source_screen is not None:
        # Evaluate the actual serialized screen assignment, using distinct
        # widget identities, then execute the packaged comparison bytecode.
        assignment=source_screen.export('Update Focused Item')['ScriptBytecode'][2]
        def evaluate(node,context):
            kind=node['$type'].split('EX_')[1].split(',')[0]
            if kind=='InstanceVariable': return context[node['Variable']['New']['Path'][0]]
            if kind=='Context': return evaluate(node['ContextExpression'],evaluate(node['ObjectExpression'],context))
            if kind=='CallMath':
                assert source_screen.data['Imports'][-node['StackNode']-1]['ObjectName']=='EqualEqual_ObjectObject'
                left,right=[evaluate(p,context) for p in node['Parameters']]
                return left is right
            raise AssertionError(kind)
        dest=assignment['VariableExpression']
        assert dest['ObjectExpression']['Variable']['New']['Path']==['Tooltip']
        field=dest['ContextExpression']['Variable']['New']
        assert field['Path']==['IC_AllowComparison']
        assert source_screen.data['Imports'][-field['ResolvedOwner']-1]['ObjectName']==STORAGE_PRIVATE+'_C'
        for screen_name in ('storage','shop'):
            player,other=object(),object()
            context={'PlayerInventoryDisplay':player,'OtherInventoryDisplay':other,'Tooltip':vm.self_}
            transitions=[
                (other,'weapon',['sword'],{'sword':'equipped sword'},[(0,'equipped sword')]),
                (player,'weapon',['sword'],{'sword':'equipped sword'},[]),
                (other,'ring',['ring1','ring2'],{'ring1':'ruby','ring2':'emerald'},[(0,'ruby'),(1,'emerald')]),
                (player,'ring',['ring1','ring2'],{'ring1':'ruby','ring2':'emerald'},[]),
                (other,'ring',['ring1','ring2'],{'ring2':'emerald'},[(1,'emerald')]),
                (None,'ring',['ring1','ring2'],{'ring2':'emerald'},[]),
                (other,'weapon',['sword'],{},[]),
                (other,'food',[],{},[]),
                (player,'shirt',['chest'],{'chest':'equipped shirt'},[]),
                (other,'shirt',['chest'],{'chest':'equipped shirt'},[(0,'equipped shirt')]),
                (other,None,[],{},[]),
                (player,'amulet',['amulet'],{'amulet':'equipped pendant'},[]),
            ]
            for source,item,slots,equipment,expected in transitions:
                context['Focused Item Source Display']=source
                allowed=evaluate(assignment['AssignmentExpression'],context)
                result=vm.run(item,slots,equipment,allow_comparison=allowed)
                assert result==expected,(screen_name,item,source is other)
                assert vm.widgets['IC_PopupAnchor']['open']==bool(expected)
                assert vm.widgets['IC_ComparisonLayer']['visibility']==(3 if expected else 1)
                if source is not other:
                    assert vm.equipment_reads==0 and not vm.shown
                    assert all(vm.widgets[f'IC_Group{i}']['visibility']==1 for i in range(2))
                source_cases+=1
        # The last allowed side must not permit a later ring-control refresh
        # on the player side. A tooltip created before the first focus is off.
        cdo=a.export('Default__'+STORAGE_PRIVATE+'_C')
        assert getprop(cdo,'IC_AllowComparison')['Value'] is False
        assert vm.run('ring',['ring1','ring2'],{'ring1':'ruby','ring2':'emerald'},allow_comparison=False)==[]
        assert not vm.widgets['IC_PopupAnchor']['open']
        source_cases+=1
        setter,refresh=source_screen.export('Update Weight And Currency')['ScriptBytecode'][-4:-2]
        assert setter['VariableExpression']['ObjectExpression']['Variable']['New']['Path']==['Tooltip']
        source_field=setter['VariableExpression']['ContextExpression']['Variable']['New']
        assert source_field['Path']==['IC_SourceInventory']
        assert source_screen.data['Imports'][-source_field['ResolvedOwner']-1]['ObjectName']==STORAGE_PRIVATE+'_C'
        assert refresh['ObjectExpression']['Variable']['New']['Path']==['Tooltip']
        assert refresh['ContextExpression']['VirtualFunctionName']=='IC_UpdateComparison'
        def notify_contents_changed(inventory):
            # Execute the packaged callback's source assignment and refresh
            # without issuing a hover, even while transfer focus is retained.
            context={'NPC Inventory':inventory,'Tooltip':vm.self_,'Force Keep Item Focus':True}
            vm.self_[source_field['Path'][0]]=evaluate(setter['AssignmentExpression'],context)
            return vm.refresh()
        for screen_name in ('storage','shop'):
            slots=['ring1','ring2']; equipment={'ring1':'ruby','ring2':'emerald'}
            assert vm.run('ring',slots,equipment)==[(0,'ruby'),(1,'emerald')]
            source=vm.self_['IC_SourceInventory']
            source['items'].pop('ring')
            assert notify_contents_changed(source)==[]
            assert vm.self_['Target Item Handle'] is None and vm.self_['IC_AllowComparison'] is True
            assert vm.fade_requested and vm.source_reads==1 and vm.equipment_reads==0
            assert not vm.widgets['IC_PopupAnchor']['open']
            assert all(vm.widgets[f'IC_Group{i}']['visibility']==1 for i in range(2))
            transfer_cases+=1
            # A later notification must not resurrect either card or restart
            # the fade after the native invalid-item transition cleared it.
            assert vm.refresh()==[] and not vm.fade_requested and vm.source_reads==0
            transfer_cases+=1
            # Failed transfers and partial stacks still have source contents.
            for remaining in (1,3):
                vm.run('ring',slots,equipment,source_quantity=5)
                source=vm.self_['IC_SourceInventory']; source['items']['ring']=remaining
                assert notify_contents_changed(source)==[(0,'ruby'),(1,'emerald')]
                assert not vm.fade_requested
                transfer_cases+=1
            # Unrelated removals must not hide a newly selected storage item.
            vm.run('new ring',slots,equipment)
            assert notify_contents_changed(vm.self_['IC_SourceInventory'])==[(0,'ruby'),(1,'emerald')]
            assert not vm.fade_requested
            transfer_cases+=1
            # Character-side items retain their normal single tooltip.
            vm.run('ring',slots,equipment,allow_comparison=False,source_quantity=0)
            assert notify_contents_changed(vm.self_['IC_SourceInventory'])==[]
            assert not vm.fade_requested and vm.source_reads==0
            transfer_cases+=1
            assert vm.run('ring',slots,equipment,source_quantity=None)==[]
            assert vm.fade_requested and vm.source_reads==0
            transfer_cases+=1
    if details is not None: details.update(source_cases=source_cases,transfer_cases=transfer_cases)
    return len(cases)+1+source_cases+transfer_cases


def verify_scroll_regression(a):
    """Ensure the input-ownership model rejects the former stock-card behavior."""
    stock=Asset(read(ROOT/'decoded/tooltip.json'))
    assert any(n.get('StackNode')==stock.imp('RegisterInputProcessor')
               for n in walk(stock.export('Update Item Display')['ScriptBytecode']))
    broken=Asset(copy.deepcopy(a.data))
    calls=[n for n in walk(broken.export('IC_UpdateComparison')['ScriptBytecode'])
           if n.get('StackNode')==broken.imp('DeregisterInputProcessor')]
    assert len(calls)==2
    # Substitute same-sized calls to retain valid branch offsets while restoring
    # the original retained-registration behavior on each passive card.
    for node in calls: node['StackNode']=broken.imp('RegisterInputProcessor')
    try:
        verify_behavior(broken)
    except AssertionError as error:
        assert str(error)=='Passive comparison retained scroll input', str(error)
    else:
        raise AssertionError('Input regression was not detected')


def verify_layout(a):
    """Check the actual packaged hierarchy against USizeBox layout contracts.

    Inject varied main/companion desired sizes at the two leaves. The test
    checks that comparison sizes cannot change the overlay's desired size,
    and that both fill slots still arrange the canvas in the main card area.
    This is a layout-contract regression, not a rendered engine test.
    """
    def children(e):
        return [a.data['Exports'][s['Value']-1] for s in getprop(e,'Slots')['Value']]
    def content(slot): return a.data['Exports'][getprop(slot,'Content')['Value']-1]
    root=a.export('IC_Root')
    primary_slot,isolation_slot=children(root)
    assert content(primary_slot)['ObjectName']=='VerticalBox_0'
    isolation=content(isolation_slot)
    assert isolation['ObjectName']=='IC_LayoutIsolation'
    assert a.data['Imports'][-isolation['ClassIndex']-1]['ObjectName']=='SizeBox'
    canvas_slot,=children(isolation)
    assert content(canvas_slot)['ObjectName']=='IC_ComparisonLayer'
    for slot in (primary_slot,isolation_slot,canvas_slot):
        assert getprop(slot,'HorizontalAlignment')['Value']=='HAlign_Fill'
        assert getprop(slot,'VerticalAlignment')['Value']=='VAlign_Fill'
        assert not any(p['Name']=='Padding' for p in slot['Data'])
    for axis in ('Width','Height'):
        assert getprop(isolation,f'bOverride_{axis}Override')['Value'] is True
        assert normalized(getprop(isolation,f'{axis}Override')['Value'])==0
    assert getprop(isolation,'Visibility')['Value']=='HitTestInvisible'
    assert not any(n.get('Name')=='Clipping' for n in walk(isolation['Data']))

    def measure(e,main_size,compare_size,shown):
        if e['ObjectName']=='VerticalBox_0': return main_size
        if e['ObjectName']=='IC_ComparisonLayer': return compare_size if shown else (0,0)
        cls=a.data['Imports'][-e['ClassIndex']-1]['ObjectName']
        if cls=='SizeBox':
            child=measure(content(children(e)[0]),main_size,compare_size,shown)
            return tuple(normalized(getprop(e,f'{axis}Override')['Value'])
                if getprop(e,f'bOverride_{axis}Override')['Value'] else child[i]
                for i,axis in enumerate(('Width','Height')))
        assert cls=='Overlay'
        sizes=[measure(content(s),main_size,compare_size,shown) for s in children(e)]
        return tuple(max(s[i] for s in sizes) for i in (0,1))

    checks=0
    for main in ((950,270),(950,550),(950,950),(950,1400)):
        for compared in ((974,400),(974,1000),(974,2400),(1200,3200)):
            for shown in (False,True):
                assert measure(root,main,compared,shown)==main
                checks+=1
    # This models the previous direct canvas/overlay edge: content could add
    # 24 logical pixels of width and a taller equipped card could add height.
    assert tuple(max(x,y) for x,y in zip((950,550),(974,1000)))!=(950,550)
    return checks


def verify_popup(a,private=PRIVATE):
    """Validate popup wiring and the single header using the packed assets.

    Deferred Slate painting itself still requires an in-game visual check.
    """
    def content(slot): return a.data['Exports'][getprop(slot,'Content')['Value']-1]
    def children(e):
        return [content(a.data['Exports'][s['Value']-1]) for s in getprop(e,'Slots')['Value']]
    anchor=a.export('IC_PopupAnchor')
    assert a.data['Imports'][-anchor['ClassIndex']-1]['ObjectName']=='MenuAnchor'
    for name,value in [('ShouldDeferPaintingAfterWindowContent',True),
                       ('UseApplicationMenuStack',False),('bFitInWindow',False)]:
        assert getprop(anchor,name)['Value'] is value
    popup_content='IC_Stack' if private==PRIVATE else 'IC_PopupContent'
    placement='MenuPlacement_RightLeftCenter' if private==PRIVATE else 'MenuPlacement_Center'
    assert getprop(anchor,'Placement')['Value']==placement
    assert getprop(anchor,'Visibility')['Value']=='HitTestInvisible'
    assert content(a.export('IC_StackSlot')) is anchor
    assert content(a.export('IC_StorageSlot')) is a.export(popup_content)
    assert getprop(a.export('IC_Stack'),'Visibility')['Value']=='HitTestInvisible'
    for member in {'IC_Stack','IC_PopupAnchor',popup_content}:
        assert any(p['Name']==member and 'FObjectProperty,' in p['$type']
                   for p in a.export(private+'_C')['LoadedProperties'])
    binding,=[b for b in getprop(a.export(private+'_C'),'Bindings')['Value']
              if any(p['Name']=='ObjectName' and p['Value']=='IC_PopupAnchor' for p in b['Value'])]
    fields={p['Name']:p['Value'] for p in binding['Value']}
    assert fields=={'ObjectName':'IC_PopupAnchor','PropertyName':'OnGetMenuContentEvent',
                    'FunctionName':'IC_GetComparisonContent','Kind':'Function'}
    provider=a.export('IC_GetComparisonContent')
    remove,return_,end=provider['ScriptBytecode']
    assert remove['ObjectExpression']['Variable']['New']['Path']==[popup_content]
    assert a.data['Imports'][-remove['ContextExpression']['StackNode']-1]['ObjectName']=='RemoveFromParent'
    assert return_['ReturnExpression']['Variable']['New']['Path']==[popup_content]
    return_prop,=provider['LoadedProperties']
    assert return_prop['Name']=='ReturnValue' and 'CPF_ReturnParm' in return_prop['PropertyFlags']
    assert a.data['Imports'][-return_prop['PropertyClass']-1]['ObjectName']=='Widget'
    assert provider['ScriptBytecodeSize']==sum(map(size,provider['ScriptBytecode']))
    fade=a.export('Fade Out')['ScriptBytecode']
    assert fade[0]['ObjectExpression']['Variable']['New']['Path']==['IC_PopupAnchor']
    assert a.data['Imports'][-fade[0]['ContextExpression']['StackNode']-1]['ObjectName']=='Close'
    stack_children=children(a.export('IC_Stack'))
    assert [e['ObjectName'] for e in stack_children]==['IC_EquippedLabel','IC_Group0','IC_Group1']
    labels=[e for e in a.data['Exports'] if e['ObjectName'].startswith('IC_EquippedLabel')]
    assert len(labels)==1 and getprop(labels[0],'Text')['CultureInvariantString']=='EQUIPPED'
    for i in range(2):
        assert [e['ObjectName'] for e in children(a.export(f'IC_Group{i}'))]==[f'IC_EquippedTooltip{i}']


def verify_inventory_boundary(original,panel,primary):
    """Exercise the outer tooltip sizing boundary missed by the inner tests.

    Vary the desired size returned by the primary ScaleBox, including changing
    width after scale/layout passes and tall clothing cards. Test the serialized
    SizeBox flags, not merely its WidthOverride value (the original value is
    present but disabled). These are sizing contracts, not a Slate render test.
    """
    def values(e): return {p['Name']:p['Value'] for p in e['Data']}
    def desired(box,child):
        data=values(box)
        return tuple(normalized(data[f'{axis}Override'])
            if data.get(f'bOverride_{axis}Override',False) else child[i]
            for i,axis in enumerate(('Width','Height')))
    width=getprop(primary.export('SizeBox_0'),'WidthOverride')['Value']
    box=panel.export('Tooltip')
    assert getprop(box,'WidthOverride')['Value']==width
    assert getprop(box,'bOverride_WidthOverride')['Value'] is True
    assert getprop(box,'bOverride_HeightOverride')['Value'] is True
    assert normalized(getprop(box,'HeightOverride')['Value'])==0
    grid_slot=panel.export('GridSlot_3')
    box_slot=panel.export('SizeBoxSlot_0')
    assert getprop(grid_slot,'Content')['Value']==panel.index('Tooltip')
    assert getprop(box_slot,'Content')['Value']==panel.index('WBP_Inventory_ItemTooltip')
    for slot in (grid_slot,box_slot):
        assert getprop(slot,'HorizontalAlignment')['Value']=='HAlign_Fill'
        assert getprop(slot,'VerticalAlignment')['Value']=='VAlign_Fill'
    assert getprop(primary.export('WidgetTree'),'RootWidget')['Value']==primary.index('IC_Root')
    assert getprop(primary.export('IC_MainSlot'),'Content')['Value']==primary.index('VerticalBox_0')
    # This transition sequence includes the return to a short card, an empty
    # hover, and changing scaled widths. Previously all those sizes escaped.
    sizes=[(950,300),(930,900),(950,1450),(890,1900),(850,2400),
           (950,600),(0,0),(950,300)]
    before=[desired(original.export('Tooltip'),s) for s in sizes]
    after=[desired(box,s) for s in sizes]
    assert len(set(before))>1,'Regression no longer exposes the old sizing path'
    assert after==[(width,0)]*len(sizes)
    # Once the tooltip contribution is constant, changing it cannot affect
    # either column's minimum or the inventory row's natural height.
    padding=values(grid_slot)['Padding']
    margins={p['Name']:p['Value'] for p in padding}
    contributions=[(w+margins.get('Left',0)+margins.get('Right',0),
                    h+margins.get('Top',0)+margins.get('Bottom',0)) for w,h in after]
    assert len(set(contributions))==1
    for inventory_height in (900,1300,1700):
        assert len({max(inventory_height,h) for _,h in contributions})==1
    # All panel functions, public fields, and unrelated widget properties must
    # remain original. Only these explicit outer layout properties may differ.
    allowed={'Tooltip':{'WidthOverride','HeightOverride','bOverride_WidthOverride','bOverride_HeightOverride'},
        'GridSlot_3':{'HorizontalAlignment','VerticalAlignment'},
        'SizeBoxSlot_0':{'HorizontalAlignment','VerticalAlignment'}}
    assert len(original.data['Exports'])==len(panel.data['Exports'])
    for before,after in zip(original.data['Exports'],panel.data['Exports']):
        assert before['ObjectName']==after['ObjectName']
        for key in ('LoadedProperties','ScriptBytecode','ScriptBytecodeSize'):
            assert normalized(before.get(key))==normalized(after.get(key))
        ignored=allowed.get(before['ObjectName'],set())
        assert normalized([p for p in before.get('Data',[]) if p['Name'] not in ignored])==normalized(
            [p for p in after.get('Data',[]) if p['Name'] not in ignored]),before['ObjectName']
    return len(sizes)


def verify_added_instructions(before,after,indices):
    """Match original instructions and branch destinations by instruction index."""
    original=before['ScriptBytecode']
    patched=after['ScriptBytecode']
    assert len(patched)==len(original)+len(indices)
    def addresses(body):
        result=[]; offset=0
        for node in body:
            result.append(offset); offset+=size(node)
        return result
    old_addresses,new_addresses=addresses(original),addresses(patched)
    retained=[i for i in range(len(patched)) if i not in indices]
    destinations={old:new_addresses[retained[i]] for i,old in enumerate(old_addresses)}
    for i,node in enumerate(original):
        relocated=copy.deepcopy(node)
        for child in walk(relocated):
            if 'CodeOffset' in child: child['CodeOffset']=destinations[child['CodeOffset']]
        assert normalized(relocated)==normalized(patched[retained[i]]),(before['ObjectName'],i)
    assert normalized(before['LoadedProperties'])==normalized(after['LoadedProperties'])
    assert after['ScriptBytecodeSize']==sum(map(size,patched))
    return [patched[i] for i in sorted(indices)]


def verify_trade_storage(primary,secondary,base,shop):
    """Verify the shared-screen integration and left-side positioning.

    Stock hover/transfer/buy/sell behavior must survive unchanged. The shared
    screen adds a source assignment and closes the popup before deactivation.
    """
    expected=Asset(rename(primary.data,PRIVATE,STORAGE_PRIVATE))
    for before in expected.data['Exports']:
        if 'FunctionExport' not in before['$type'] or before['ObjectName']=='IC_GetComparisonContent': continue
        after=secondary.export(before['ObjectName'])
        if before['ObjectName']=='IC_UpdateComparison':
            body=after['ScriptBytecode']
            gate,valid,quantity,reset,_=verify_added_instructions(before,after,{5,7,8,len(body)-3,len(body)-2})
            assert 'EX_JumpIfNot,' in gate['$type']
            assert gate['BooleanExpression']['Variable']['New']['Path']==['IC_AllowComparison']
            assert gate['CodeOffset']==sum(map(size,body[:-4]))
            assert valid['CodeOffset']==quantity['CodeOffset']==sum(map(size,body[:-3]))
            assert reset['VirtualFunctionName']=='Set Item'
            handle,count,equippable,list_item=reset['Parameters']
            assert 'EX_NoObject,' in list_item['$type']
            assert 'EX_StructConst,' in handle['$type'] and handle['Value']==[] and handle['StructSize']==4
            assert secondary.data['Imports'][-handle['Struct']-1]['ObjectName']=='ItemHandle'
            assert 'EX_IntConst,' in count['$type'] and count['Value']==0
            assert 'EX_False,' in equippable['$type']
            assert valid['BooleanExpression']['Parameters'][0]['Variable']['New']['Path']==['IC_SourceInventory']
            continue
        for key in ('LoadedProperties','ScriptBytecode','ScriptBytecodeSize'):
            assert normalized(before[key])==normalized(after[key]),('shared comparison logic',before['ObjectName'])

    for filename,patched in [('double-inventory',base),('shop',shop)]:
        original=Asset(read(ROOT/'decoded'/f'{filename}.json'))
        assert len(original.data['Exports'])==len(patched.data['Exports'])
        assert len(original.data['Imports'])==len(patched.data['Imports'])
        for before,after in zip(original.data['Exports'],patched.data['Exports']):
            assert before['ObjectName']==after['ObjectName']
            for key in ('LoadedProperties','Data'):
                assert normalized(before.get(key))==normalized(after.get(key)),(filename,before['ObjectName'],key)
            if filename=='double-inventory' and before['ObjectName']=='BP_OnDeactivated':
                close,*rest=after['ScriptBytecode']
                assert close['ObjectExpression']['Variable']['New']['Path']==['Tooltip']
                assert close['ContextExpression']['VirtualFunctionName']=='Fade Out'
                assert normalized(rest)==normalized(before['ScriptBytecode'])
                assert after['ScriptBytecodeSize']==before['ScriptBytecodeSize']+size(close)
            elif filename=='double-inventory' and before['ObjectName']=='Update Focused Item':
                assignment,source=verify_added_instructions(before,after,{2,3})
                assert 'EX_LetBool,' in assignment['$type']
                assert source['VariableExpression']['ContextExpression']['Variable']['New']['Path']==['IC_SourceInventory']
                assert source['AssignmentExpression']['Variable']['New']['Path']==['NPC Inventory']
                assert after['ScriptBytecode'][4]['VirtualFunctionName']=='Prepare Tooltip'
            elif filename=='double-inventory' and before['ObjectName']=='Update Weight And Currency':
                body=after['ScriptBytecode']
                source,refresh=body[-4:-2]
                assert not any('CodeOffset' in n for n in walk(before['ScriptBytecode']))
                assert normalized(before['ScriptBytecode'][:-2])==normalized(body[:-4])
                assert normalized(before['ScriptBytecode'][-2:])==normalized(body[-2:])
                assert after['ScriptBytecodeSize']==before['ScriptBytecodeSize']+size(source)+size(refresh)
                assert source['VariableExpression']['ContextExpression']['Variable']['New']['Path']==['IC_SourceInventory']
                assert refresh['ContextExpression']['VirtualFunctionName']=='IC_UpdateComparison'
            else:
                for key in ('ScriptBytecode','ScriptBytecodeSize'):
                    assert normalized(before.get(key))==normalized(after.get(key)),(filename,before['ObjectName'],key)
        for before,after in zip(original.data['Imports'],patched.data['Imports']):
            changed={key for key in before if before[key]!=after[key]}
            assert changed <= {'ObjectName','ClassPackage','ClassName'}
            for key in changed:
                assert after[key]==before[key].replace(ORIGINAL,STORAGE_PRIVATE)
        assert not any(imp['ObjectName']==ORIGINAL+'_C' for imp in patched.data['Imports'])
    assert base.data['Imports'][-base.export('Tooltip')['ClassIndex']-1]['ObjectName']==STORAGE_PRIVATE+'_C'
    # Verify the actual inventory-content delegates reach the refreshed handler.
    uber=base.export('ExecuteUbergraph_WBP_DoubleInventoryBase')['ScriptBytecode']
    sources=[]
    for index,node in enumerate(uber):
        if 'EX_AddMulticastDelegate,' not in node['$type']: continue
        binding=uber[index-1]
        if binding.get('FunctionName')!='Update Weight And Currency': continue
        delegate=node['Delegate']
        assert delegate['ContextExpression']['Variable']['New']['Path']==['OnInventoryContentsChanged']
        sources.append(delegate['ObjectExpression']['Variable']['New']['Path'][0])
    assert set(sources)=={'Player Inventory','NPC Inventory'}
    # The shop still changes ShowSellCost on the correct class, so price mode
    # follows the selected side exactly as it did in the original game.
    shop_price=next(n for n in walk(shop.export('Prepare Tooltip')['ScriptBytecode'])
                    if n.get('Path')==['ShowSellCost'])
    assert shop.data['Imports'][-shop_price['ResolvedOwner']-1]['ObjectName']==STORAGE_PRIVATE+'_C'
    # Shop's override calls the shared deactivation handler; storage inherits it.
    assert any('EX_LocalFinalFunction,' in n.get('$type','') and n.get('StackNode',0)<0
        and shop.data['Imports'][-n['StackNode']-1]['ObjectName']=='BP_OnDeactivated'
        for n in walk(shop.export('ExecuteUbergraph_WBP_Shop_New')['ScriptBytecode']))
    assert not any(e['ObjectName']=='BP_OnDeactivated' for e in read(ROOT/'decoded/storage.json')['Exports'])

    box=secondary.export('IC_PopupContent')
    width=getprop(secondary.export('SizeBox_0'),'WidthOverride')['Value']
    assert getprop(box,'WidthOverride')['Value']==width
    assert getprop(box,'bOverride_WidthOverride')['Value'] is True
    assert getprop(box,'Visibility')['Value']=='HitTestInvisible'
    assert not any(p['Name']=='bOverride_HeightOverride' and p['Value'] for p in box['Data'])
    slot=secondary.export('IC_PopupContentSlot')
    assert getprop(slot,'Parent')['Value']==secondary.index('IC_PopupContent')
    assert getprop(slot,'Content')['Value']==secondary.index('IC_Stack')
    assert getprop(slot,'HorizontalAlignment')['Value']=='HAlign_Fill'
    layout=getprop(secondary.export('IC_StackSlot'),'LayoutData')['Value']
    anchors=normalized(next(p for p in layout if p['Name']=='Anchors')['Value'])
    assert all(v['Value'][0]['Value']['X']==0 and v['Value'][0]['Value']['Y']==0.5 for v in anchors)
    offsets={p['Name']:normalized(p['Value']) for p in next(p for p in layout if p['Name']=='Offsets')['Value']}
    assert offsets=={'Left':-(width/2+24),'Top':0}
    cases=0
    for scale in (0.5,0.75,1,1.25):
        for primary_height,popup_height in ((500,700),(1200,400),(900,1900),(600,2700)):
            center_x=offsets['Left']*scale
            right_edge=center_x+width*scale/2
            assert right_edge==-24*scale
            center_y=primary_height*scale/2
            top=center_y-popup_height*scale/2
            assert top+popup_height*scale/2==center_y
            cases+=1
    return cases


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-paks',type=Path,required=True)
    parser.add_argument('--reference-root',type=Path,help='Optional original extracted asset tree')
    parser.add_argument('--variant',choices=VARIANTS,default='default')
    args=parser.parse_args()
    gui,retoc=SOURCE_ROOT/'tools/UAssetGUI.exe',SOURCE_ROOT/'tools/retoc.exe'
    work,dist=release_paths(args.variant)
    containers,refs,verified=work/'verify-containers',ROOT/'reference-stage',work/'verified'
    containers.mkdir(parents=True,exist_ok=True)
    expected=[]
    asset_paths=[UI/'Tooltip'/f'{PRIVATE}.uasset',UI/'WBP_InventoryPanel.uasset']+STORAGE_ASSETS
    packaged=set(asset_paths)
    def copy_reference(ref):
        if ref.with_suffix('.uasset') in packaged: return
        src=(ROOT/'extracted'/ref).with_suffix('.uasset')
        if not src.exists() and args.reference_root:
            for suffix in ('.uasset','.uexp','.ubulk'):
                source=(args.reference_root/ref).with_suffix(suffix)
                if source.exists():
                    target=src.with_suffix(suffix); target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(source.read_bytes())
        assert src.exists(),f'Missing reference asset: {ref}'
        for suffix in ('.uasset','.uexp','.ubulk'):
            source=src.with_suffix(suffix)
            if source.exists():
                target=(refs/ref).with_suffix(suffix); target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(source.read_bytes())
    for rel in asset_paths:
        data=read((work/'extracted'/rel).with_suffix('.json'))
        expected.append((rel,data))
        for imp in data['Imports']:
            name=imp['ObjectName']
            if imp['ClassName']!='Package' or not name.startswith('/Game/'): continue
            ref=Path('Dawnwalker/Content')/name[len('/Game/'):]
            copy_reference(ref)
    # Referenced Blueprint schemas may themselves use Blueprint enums/structs.
    # Include their real symbol definitions instead of tolerating UnknownExport.
    seen=set()
    while True:
        pending=[p for p in refs.rglob('*.uasset') if p.stem.startswith(('WBP_','BP_')) and p not in seen]
        if not pending: break
        for p in pending:
            seen.add(p)
            output=ROOT/'schema-cache'/p.with_suffix('.json').name
            output.parent.mkdir(exist_ok=True)
            if not output.exists(): run(gui,'tojson',ROOT/'extracted'/p.relative_to(refs),output,'VER_UE5_5',MAPPING)
            schema=read(output)
            for imp in schema['Imports']:
                if imp['ClassName'] not in ('UserDefinedEnum','UserDefinedStruct','BlueprintGeneratedClass','WidgetBlueprintGeneratedClass'): continue
                if imp['OuterIndex']>=0: continue
                package=schema['Imports'][-imp['OuterIndex']-1]['ObjectName']
                if package.startswith('/Game/'):
                    copy_reference(Path('Dawnwalker/Content')/package[len('/Game/'):])
    # Read script symbols extracted from the installed game, not a live process.
    game=args.game_paks
    for suffix in ('.utoc','.ucas'):
        (containers/('global'+suffix)).write_bytes((game/('global'+suffix)).read_bytes())
    run(retoc,'to-zen',refs,containers/'references.utoc','--version','UE5_5')
    for suffix in ('.utoc','.ucas','.pak'):
        (containers/(STEM+suffix)).write_bytes((dist/(STEM+suffix)).read_bytes())
    run(retoc,'verify',containers/(STEM+'.utoc'))
    run(retoc,'to-legacy',containers,verified,'--version','UE5_5','--no-shaders')
    checked=[]
    for rel,data in expected:
        output=verified/(rel.stem+'.json')
        output.unlink(missing_ok=True)
        run(gui,'tojson',verified/rel,output,'VER_UE5_5',MAPPING)
        assert output.exists(),f'Decoder did not produce {output}'
        actual=read(output)
        assert len(actual['Imports'])==len(data['Imports'])
        for before,after in zip(data['Imports'],actual['Imports']):
            assert before==after,(rel,'import',before,after)
        assert len(actual['Exports'])==len(data['Exports'])
        for before,after in zip(data['Exports'],actual['Exports']):
            assert before['ObjectName']==after['ObjectName']
            assert 'RawExport' not in after['$type']
            for key in ('LoadedProperties','Data','ScriptBytecode','ScriptBytecodeSize','Extras'):
                if key in before:
                    assert normalized(before[key])==normalized(after[key]),(rel,before['ObjectName'],key)
        checked.append(str(rel))
    primary=Asset(read(verified/(PRIVATE+'.json')))
    cases=verify_behavior(primary)
    layout_cases=verify_layout(primary)
    verify_popup(primary)
    original=Asset(rename(read(ROOT/'decoded/tooltip.json'),ORIGINAL,PRIVATE))
    for before in original.data['Exports']:
        if 'FunctionExport' not in before['$type'] or before['ObjectName'] in ('Set Item','SetComparedItemSlot','Fade Out','OnScrolled'): continue
        after=primary.export(before['ObjectName'])
        for key in ('ScriptBytecode','ScriptBytecodeSize','LoadedProperties'):
            assert normalized(before[key])==normalized(after[key]),('original function changed',before['ObjectName'])
    original_panel=Asset(read(ROOT/'decoded/panel.json'))
    patched_panel=Asset(read(verified/'WBP_InventoryPanel.json'))
    inventory_cases=verify_inventory_boundary(original_panel,patched_panel,primary)
    secondary=Asset(read(verified/(STORAGE_PRIVATE+'.json')))
    for tooltip in (primary,secondary): verify_scroll_regression(tooltip)
    shared_scroll_cases=sum(verify_shared_scroll(tooltip) for tooltip in (primary,secondary))
    stock_widgets=verify_patch11_stock_widgets(primary,secondary)
    localization_cases = {PRIVATE:verify_localization(primary,PRIVATE,args.variant),
                          STORAGE_PRIVATE:verify_localization(secondary,STORAGE_PRIVATE,args.variant)}
    lifecycle=verify_lifecycle(secondary)
    storage_stats={}
    storage_cases=verify_behavior(secondary,Asset(read(verified/'WBP_DoubleInventoryBase.json')),storage_stats)
    storage_layout_cases=verify_layout(secondary)
    verify_popup(secondary,STORAGE_PRIVATE)
    trade_storage_cases=verify_trade_storage(primary,secondary,
        Asset(read(verified/'WBP_DoubleInventoryBase.json')),Asset(read(verified/'WBP_Shop_New.json')))
    # Root anchor and alignment both use Y=0.5, so a single card or both rings
    # remain centered against the hovered tooltip as their heights change.
    anchor=getprop(primary.export('IC_StackSlot'),'LayoutData')['Value']
    anchors=next(p for p in anchor if p['Name']=='Anchors')['Value']
    assert all(v['Value'][0]['Value']=={'$type':'UAssetAPI.UnrealTypes.FVector2D, UAssetAPI','X':1.0,'Y':0.5} for v in anchors)
    assert next(p for p in anchor if p['Name']=='Alignment')['Value'][0]['Value']['Y']==0.5
    for tooltip in (primary,secondary):
        for i in range(2):
            card=tooltip.export(f'IC_EquippedTooltip{i}')
            assert tooltip.data['Imports'][-card['ClassIndex']-1]['ObjectName']==ORIGINAL+'_C','Recursive tooltip!'
            assert getprop(card,'Visibility')['Value']=='HitTestInvisible'
    assert {p.relative_to(work/'staging') for p in (work/'staging').rglob('*.uasset')}==packaged
    report={'version':VERSION,'variant':args.variant,'status':'static checks passed','game_runtime_verified':False,'verified_assets':checked,
            'game_version':'1.1','stock_widget_preservation_cases':stock_widgets,
            'control_flow_cases':cases,'layout_contract_cases':layout_cases,
            'inventory_boundary_cases':inventory_cases,
            'shop_storage_control_flow_cases':storage_cases,'shop_storage_layout_cases':storage_layout_cases,
            'shop_storage_source_filter_cases':storage_stats['source_cases'],
            'shop_storage_transfer_cases':storage_stats['transfer_cases'],
            'tooltip_lifecycle_recovery_cases':lifecycle['recovery_cases'],
            'v1_1_0_regression_reproduced':lifecycle['v1_1_0_regression_reproduced'],
            'heading_localization_cases':localization_cases,
            'shop_storage_position_cases':trade_storage_cases,
            'shared_scroll_cases':shared_scroll_cases,
            'checks':['mouse and fractional controller scroll forwarded to visible comparisons',
            'independent stock scroll clamping and closed-popup suppression',
            'main-only scrolling regression detected',
            'passive comparison scroll input released before popup and after refresh',
            'primary scroll input ownership preserved in model','retained-input regression detected for both tooltip classes',
            'resolved import round trip','bytecode/signature/property round trip',
            'original inventory panel schema and functions preserved','original tooltip functions preserved',
            'equipped-item hover suppression','comparison layout size isolation',
            'fixed outer tooltip contribution to inventory grid',
            'deferred nonfocusing popup wiring and lifecycle','single shared equipped header',
            'centered stack layout','nonrecursive stock equipped tooltips','read-only equipment lookup',
            'shop and storage tooltip routing','shop buy/sell price mode preserved',
            'shop and storage transaction functions preserved','shared screen close cleanup',
            'fixed-width left-side centered popup','only storage and merchant source comparisons',
            'player-side hover and ring refresh suppression','cross-side stale popup cleanup',
            'live source membership after transfers','inventory-content event refresh during retained focus',
            'stale primary and comparison tooltip reset','remaining source items retain comparisons',
            'v1.1.0 post-purchase hidden tooltip reproduced',
            'stock cached-asset reset and next-hover fade-in recovery',
            'repeated purchases without reopening shop','bounded invalid-item cleanup reentry',
            'active game text language heading binding','Unicode heading text round trip',
            'regional language tags and English fallback','heading language changes in the same widget'],
            'payloads':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in dist.glob(STEM+'.*')}}
    if args.variant == 'russian-heading':
        report['checks'].append('optional Russian heading for the English text slot')
    write(work/'verification-report.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
