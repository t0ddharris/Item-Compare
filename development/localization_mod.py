"""Select the comparison heading from the game's active text language.

The native Text delegate reevaluates the getter, including after a language
change. This does not change the game's culture, locale, or localization data.
"""
import copy

from build_mod import PRIVATE, ex, var, ptr, prop, struct, enum, size, getprop


HEADER_FUNCTION = 'IC_GetEquippedHeading'
# An exact tag is always accepted; True also accepts its regional extensions.
# Do not treat all zh tags as Simplified Chinese: Hant/TW/HK/MO stay English.
HEADINGS = (
    ('已装备', (('zh-Hans', True), ('zh-CN', True), ('zh-SG', True), ('zh', False))),
    ('EQUIPADO', (('es', True),)),
    ('EQUIPADO', (('pt-BR', True), ('pt', False))),
    ('AUSGERÜSTET', (('de', True),)),
    ('装備中', (('ja', True),)),
    ('WYPOSAŻONO', (('pl', True),)),
    ('장착 중', (('ko', True),)),
    ('ЭКИПИРОВАНО', (('ru', True),)),
)
FALLBACK = 'EQUIPPED'


def add_localized_header(a, variant='default'):
    assert variant in ('default', 'russian-heading'), variant
    cls = a.export(PRIVATE + '_C')
    owner = len(a.data['Exports']) + 1
    internationalization = a.add_import('KismetInternationalizationLibrary',
                                       a.imp('/Script/Engine'), cn='Class')
    current_language = a.add_import('GetCurrentLanguage', internationalization)
    equals = a.add_import('EqualEqual_StriStri', a.imp('KismetStringLibrary'))
    starts_with = a.add_import('StartsWith', a.imp('KismetStringLibrary'))
    to_text = a.add_import('Conv_StringToText', a.imp('KismetTextLibrary'))

    templates = a.export('Get Item Category Localized Text')['LoadedProperties']
    language = copy.deepcopy(next(p for p in templates if p['SerializedType'] == 'StrProperty'))
    language.update(Name='Language', PropertyFlags='CPF_None')
    result = copy.deepcopy(next(p for p in templates if p['Name'] == 'Result'))
    result.update(Name='ReturnValue', PropertyFlags='CPF_Parm, CPF_OutParm, CPF_ReturnParm')

    def native(function, *args):
        return ex('CallMath', StackNode=function, Parameters=list(args))

    def literal(value):
        return ex('StringConst' if value.isascii() else 'UnicodeStringConst', Value=value)

    def any_of(conditions):
        condition = conditions[0]
        for other in conditions[1:]:
            condition = native(a.imp('BooleanOR'), condition, other)
        return condition

    def matches(tags):
        conditions = []
        for tag, regional in tags:
            conditions.append(native(equals, var('Language', owner, True), literal(tag)))
            if regional:
                conditions.append(native(starts_with, var('Language', owner, True),
                                         literal(tag + '-'), ex('ByteConst', Value=0)))
        return any_of(conditions)

    def return_text(value):
        return ex('Return', ReturnExpression=native(to_text, literal(value)))

    body = [ex('Let', Value=ptr('Language', owner), Variable=var('Language', owner, True),
               Expression=native(current_language))]
    # Some Russian fan translations occupy the English slot. This is an
    # explicit optional download, never inferred from a player's OS or files.
    headings = HEADINGS
    if variant == 'russian-heading':
        headings += (('ЭКИПИРОВАНО', (('en', True),)),)
    for text, tags in headings:
        branch = ex('JumpIfNot', CodeOffset=0, BooleanExpression=matches(tags))
        body.extend((branch, return_text(text)))
        branch['CodeOffset'] = sum(map(size, body))
    body.extend((return_text(FALLBACK), ex('EndOfScript')))

    fn = copy.deepcopy(a.export('IC_GetComparisonContent'))
    fn.update(ObjectName=HEADER_FUNCTION,
              FunctionFlags='FUNC_Public, FUNC_HasOutParms, FUNC_HasDefaults, FUNC_BlueprintCallable, FUNC_BlueprintPure',
              LoadedProperties=[result, language], ScriptBytecode=body,
              ScriptBytecodeSize=sum(map(size, body)))
    assert a.append(fn) == owner
    cls['FuncMap'].append([HEADER_FUNCTION, owner])
    cls['Children'].append(owner)
    cls['CreateBeforeSerializationDependencies'].append(owner)

    bindings = getprop(cls, 'Bindings')['Value']
    bindings.append(struct(str(len(bindings)), 'DelegateRuntimeBinding', [
        prop('ObjectName', 'IC_EquippedLabel', 'Objects.StrPropertyData'),
        prop('PropertyName', 'Text', 'Objects.NamePropertyData'),
        prop('FunctionName', HEADER_FUNCTION, 'Objects.NamePropertyData'),
        enum('Kind', 'EBindingKind', 'Function'),
    ]))
