"""Left-side comparison wiring for the shared shop/storage screen.

Keep the accepted inventory assets unchanged and reuse their comparison logic.
"""
import copy

from build_mod import (ROOT, UI, PRIVATE, ORIGINAL, Asset, read, rename, prop,
                       enum, widget, getprop, var, ptr, ex,
                       ctx, call, size, walk)

STORAGE_PRIVATE = 'WBP_IC_TradeStorageTooltip'
STORAGE_UI = UI.parent.parent/'ShopAndStorage'
STORAGE_ASSETS = [UI/'Tooltip'/f'{STORAGE_PRIVATE}.uasset',
                  STORAGE_UI/'WBP_DoubleInventoryBase.uasset',
                  STORAGE_UI/'Shop/WBP_Shop_New.uasset']


def redirect_tooltip_imports(asset):
    old_path='/Game/_Dawnwalker/UI/_Unified/GameHub/Inventory/Tooltip/'+ORIGINAL
    for imp in asset.data['Imports']:
        if imp['ObjectName'] in (old_path,ORIGINAL+'_C','Default__'+ORIGINAL+'_C'):
            imp['ObjectName']=imp['ObjectName'].replace(ORIGINAL,STORAGE_PRIVATE)
        if imp['ClassPackage']==old_path: imp['ClassPackage']=old_path.replace(ORIGINAL,STORAGE_PRIVATE)
        if imp['ClassName']==ORIGINAL+'_C': imp['ClassName']=STORAGE_PRIVATE+'_C'


def build_storage_assets(primary):
    a=Asset(rename(copy.deepcopy(primary),PRIVATE,STORAGE_PRIVATE))
    owner,tree=a.index(STORAGE_PRIVATE+'_C'),a.index('WidgetTree')
    cls=a.data['Exports'][owner-1]
    # The shared screen opts in only for OtherInventoryDisplay. Keep the
    # decision on the tooltip so ring-comparison refreshes honor it too.
    allowed=copy.deepcopy(next(p for p in cls['LoadedProperties'] if p['Name']=='Equippable'))
    allowed.update(Name='IC_AllowComparison',Value=False)
    cls['LoadedProperties'].append(allowed)
    a.export('Default__'+STORAGE_PRIVATE+'_C')['Data'].append(
        prop('IC_AllowComparison',False,'Objects.BoolPropertyData'))
    source_member=copy.deepcopy(next(p for p in cls['LoadedProperties'] if p['Name']=='SizeBox_0'))
    source_member.update(Name='IC_SourceInventory',PropertyClass=a.imp('InventoryComponent'))
    cls['LoadedProperties'].append(source_member)
    comparison=a.export('IC_UpdateComparison')
    body=comparison['ScriptBytecode']
    # Close and clear the previous popup before applying the source filter.
    # Switching from storage/vendor to player items must clear both cards.
    gate=ex('JumpIfNot',CodeOffset=0,BooleanExpression=var('IC_AllowComparison',owner))
    insert_before=5
    insertion=sum(map(size,body[:insert_before]))
    for node in walk(body):
        if 'CodeOffset' in node and node['CodeOffset']>=insertion:
            node['CodeOffset']+=size(gate)
    gate['CodeOffset']=sum(map(size,body[:-2]))+size(gate)
    body.insert(insert_before,gate)
    # A globally valid item handle can survive a transfer. The last hovered
    # display alone is insufficient: require current membership in its source.
    # Query the native count directly. The stock quantity-display helper
    # substitutes 1 for nonstackable items even when they left the inventory.
    get_quantity=a.add_import('GetItemQuantity',a.imp('InventoryComponent'))
    object_valid=a.add_import('IsValid',a.imp('KismetSystemLibrary'))
    source=var('IC_SourceInventory',owner)
    membership=[ex('JumpIfNot',CodeOffset=0,BooleanExpression=ex('CallMath',StackNode=object_valid,
                    Parameters=[copy.deepcopy(source)])),
                ex('JumpIfNot',CodeOffset=0,BooleanExpression=ex('CallMath',StackNode=a.imp('Greater_IntInt'),
                    Parameters=[ctx(copy.deepcopy(source),ex('FinalFunction',StackNode=get_quantity,
                        Parameters=[var('Target Item Handle',owner),ex('False')])),ex('IntConst',Value=0)]))]
    # Keep the existing invalid-handle check before querying the source.
    insert_before=7
    insertion=sum(map(size,body[:insert_before]))
    extra=sum(map(size,membership))
    for node in walk(body):
        if 'CodeOffset' in node and node['CodeOffset']>=insertion: node['CodeOffset']+=extra
    body[insert_before:insert_before]=membership
    # Normal paths retain their Return. Missing source/item paths use the
    # stock invalid-item transition. Calling Fade Out alone leaves Target
    # Item Asset valid, so later valid hovers skip Fade In and remain hidden.
    body.pop()  # Move EndOfScript after the additional return path.
    missing_address=sum(map(size,body))
    for branch in membership: branch['CodeOffset']=missing_address
    body += [call('Set Item',ex('StructConst',Struct=a.imp('ItemHandle'),StructSize=4,Value=[]),
                  ex('IntConst',Value=0),ex('False'),ex('NoObject')),
             ex('Return',ReturnExpression=ex('Nothing')),ex('EndOfScript')]
    comparison['ScriptBytecodeSize']=sum(map(size,body))
    # A fixed-width popup gives Center placement an exact left edge without
    # estimating either card's height. Its right edge is always 24 units left
    # of the hovered card, and its vertical center follows that card's center.
    width=getprop(a.export('SizeBox_0'),'WidthOverride')['Value']
    box=widget(a,a.export('IC_LayoutIsolation'),'IC_PopupContent',a.imp('SizeBox'),
        a.imp('Default__SizeBox'),tree,[
            prop('WidthOverride',width,'Objects.FloatPropertyData'),
            prop('bOverride_WidthOverride',True,'Objects.BoolPropertyData'),
            prop('bIsVariable',True,'Objects.BoolPropertyData'),
            enum('Visibility','ESlateVisibility','HitTestInvisible')])
    stack=a.index('IC_Stack')
    box_slot=widget(a,a.export('IC_IsolationSlot'),'IC_PopupContentSlot',a.imp('SizeBoxSlot'),
        a.imp('Default__SizeBoxSlot'),box,[
            enum('HorizontalAlignment','EHorizontalAlignment','HAlign_Fill'),
            enum('VerticalAlignment','EVerticalAlignment','VAlign_Fill'),
            prop('Parent',box),prop('Content',stack)])
    box_exp=a.data['Exports'][box-1]
    box_exp['Data'] += [prop('Slots',[prop('0',box_slot)],'Objects.ArrayPropertyData',
                             ArrayType='ObjectProperty'),prop('Slot',a.index('IC_StorageSlot'))]
    box_exp['CreateBeforeSerializationDependencies'] += [box_slot,a.index('IC_StorageSlot')]
    stack_exp=a.export('IC_Stack')
    old_slot=getprop(stack_exp,'Slot')['Value']
    getprop(stack_exp,'Slot')['Value']=box_slot
    stack_exp['CreateBeforeSerializationDependencies']=[
        box_slot if idx==old_slot else idx for idx in stack_exp['CreateBeforeSerializationDependencies']]
    storage_slot=a.export('IC_StorageSlot')
    getprop(storage_slot,'Content')['Value']=box
    storage_slot['CreateBeforeSerializationDependencies']=[a.index('IC_ComparisonLayer'),box]
    member=copy.deepcopy(next(p for p in cls['LoadedProperties'] if p['Name']=='SizeBox_0'))
    member['Name']='IC_PopupContent'
    cls['LoadedProperties'].append(member)
    provider=a.export('IC_GetComparisonContent')
    for node in walk(provider['ScriptBytecode']):
        if node.get('Path')==['IC_Stack']: node['Path']=['IC_PopupContent']
    getprop(a.export('IC_PopupAnchor'),'Placement')['Value']='MenuPlacement_Center'
    for slot_name in ('IC_StackSlot','IC_StorageSlot'):
        layout=getprop(a.export(slot_name),'LayoutData')['Value']
        offsets=next(p for p in layout if p['Name']=='Offsets')['Value']
        next(p for p in offsets if p['Name']=='Left')['Value']=-(width/2+24.0)
        anchors=next(p for p in layout if p['Name']=='Anchors')['Value']
        for anchor in anchors: anchor['Value'][0]['Value']['X']=0.0
    a.names()

    # Preserve all shared screen properties/functions and the inherited class
    # identity. The replacement has the stock schema plus private members.
    base=Asset(read(ROOT/'decoded/double-inventory.json'))
    redirect_tooltip_imports(base)
    base_owner=base.index('WBP_DoubleInventoryBase_C')
    tooltip_owner=base.imp(STORAGE_PRIVATE+'_C')
    update=base.export('Update Focused Item')
    body=update['ScriptBytecode']
    scope=ex('LetBool',VariableExpression=ctx(var('Tooltip',base_owner),
        var('IC_AllowComparison',tooltip_owner),ptr('IC_AllowComparison',tooltip_owner)),
        AssignmentExpression=ex('CallMath',StackNode=base.imp('EqualEqual_ObjectObject'),
            Parameters=[var('Focused Item Source Display',base_owner),var('OtherInventoryDisplay',base_owner)]))
    # Insert after the stock Force Keep Item Focus guard and before the
    # virtual Prepare Tooltip hook, which the shop overrides for prices.
    insert_before=next(i for i,node in enumerate(body) if node.get('VirtualFunctionName')=='Prepare Tooltip')
    insertion=sum(map(size,body[:insert_before]))
    for node in walk(body):
        if 'CodeOffset' in node and node['CodeOffset']>=insertion:
            node['CodeOffset']+=size(scope)
    body.insert(insert_before,scope)
    source_assignment=ex('LetObj',VariableExpression=ctx(var('Tooltip',base_owner),
        var('IC_SourceInventory',tooltip_owner),ptr('IC_SourceInventory',tooltip_owner)),
        AssignmentExpression=var('NPC Inventory',base_owner))
    insertion=sum(map(size,body[:insert_before+1]))
    for node in walk(body):
        if 'CodeOffset' in node and node['CodeOffset']>=insertion:
            node['CodeOffset']+=size(source_assignment)
    body.insert(insert_before+1,copy.deepcopy(source_assignment))
    update['ScriptBytecodeSize']=sum(map(size,body))
    # Both real inventories already notify this handler on content changes.
    # Refresh independently of the transfer's Force Keep Item Focus window;
    # no new hover or polling is needed to close a removed item's popup.
    changed=base.export('Update Weight And Currency')
    assert not any('CodeOffset' in node for node in walk(changed['ScriptBytecode']))
    changed['ScriptBytecode'][-2:-2]=[copy.deepcopy(source_assignment),
        ctx(var('Tooltip',base_owner),call('IC_UpdateComparison'))]
    changed['ScriptBytecodeSize']+=size(source_assignment)+size(changed['ScriptBytecode'][-3])
    # The shared screen's close path does not call tooltip Fade Out itself.
    # Close the deferred popup before the original shop/storage teardown.
    end=base.export('BP_OnDeactivated')
    end['ScriptBytecode'].insert(0,ctx(var('Tooltip',base.index('WBP_DoubleInventoryBase_C')),call('Fade Out')))
    end['ScriptBytecodeSize']=sum(map(size,end['ScriptBytecode']))
    base.names()
    # Shop's Prepare Tooltip writes ShowSellCost through a typed property
    # pointer. Redirect its owner too, preserving all buy/sell logic and prices.
    shop=Asset(read(ROOT/'decoded/shop.json'))
    redirect_tooltip_imports(shop)
    shop.names()
    return list(zip([a.data,base.data,shop.data],STORAGE_ASSETS))
