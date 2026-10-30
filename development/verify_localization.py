"""Exercise the heading getter decoded from each actual packaged tooltip."""
from build_mod import getprop, size, walk
from localization_mod import HEADER_FUNCTION


def verify_localization(a, private, variant='default'):
    assert variant in ('default', 'russian-heading'), variant
    cls = a.export(private + '_C')
    bindings = [{p['Name']: p['Value'] for p in entry['Value']}
                for entry in getprop(cls, 'Bindings')['Value']]
    assert len(bindings) == 2
    assert {'ObjectName': 'IC_EquippedLabel', 'PropertyName': 'Text',
            'FunctionName': HEADER_FUNCTION, 'Kind': 'Function'} in bindings
    assert sum(b['ObjectName'] == 'IC_EquippedLabel' for b in bindings) == 1
    fn = a.export(HEADER_FUNCTION)
    fn_owner = a.index(HEADER_FUNCTION)
    assert [HEADER_FUNCTION, fn_owner] in cls['FuncMap']
    assert fn_owner in cls['Children'] and fn_owner in cls['CreateBeforeSerializationDependencies']
    assert 'FUNC_BlueprintPure' in fn['FunctionFlags']
    return_prop, language = fn['LoadedProperties']
    assert return_prop['Name'] == 'ReturnValue' and return_prop['SerializedType'] == 'TextProperty'
    assert set(return_prop['PropertyFlags'].split(', ')) == {'CPF_Parm', 'CPF_OutParm', 'CPF_ReturnParm'}
    assert language['Name'] == 'Language' and language['SerializedType'] == 'StrProperty'
    assert language['PropertyFlags'] == 'CPF_None'

    ops, offset = {}, 0
    for op in fn['ScriptBytecode']:
        ops[offset] = op
        offset += size(op)
    assert offset == fn['ScriptBytecodeSize']
    for node in walk(fn['ScriptBytecode']):
        if 'CodeOffset' in node:
            assert node['CodeOffset'] in ops
        if 'EX_LocalVariable,' in node.get('$type', ''):
            assert node['Variable']['New'] == {
                '$type': 'UAssetAPI.UnrealTypes.FFieldPath, UAssetAPI',
                'Path': ['Language'], 'ResolvedOwner': fn_owner}

    def import_path(index):
        parts = []
        while index:
            assert index < 0
            imp = a.data['Imports'][-index - 1]
            parts.append(imp['ObjectName'])
            index = imp['OuterIndex']
        return tuple(reversed(parts))

    allowed = {
        ('/Script/Engine', 'KismetInternationalizationLibrary', 'GetCurrentLanguage'),
        ('/Script/Engine', 'KismetStringLibrary', 'EqualEqual_StriStri'),
        ('/Script/Engine', 'KismetStringLibrary', 'StartsWith'),
        ('/Script/Engine', 'KismetMathLibrary', 'BooleanOR'),
        ('/Script/Engine', 'KismetTextLibrary', 'Conv_StringToText'),
    }
    native_calls = [n for n in walk(fn['ScriptBytecode']) if 'EX_CallMath,' in n.get('$type', '')]
    assert {import_path(n['StackNode']) for n in native_calls} == allowed
    assert sum(import_path(n['StackNode'])[-1] == 'GetCurrentLanguage' for n in native_calls) == 1

    class VM:
        """Reuse one bound getter while changing the engine's active language."""
        current_language = 'en'

        def evaluate(self):
            self.locals = {}
            self.language_reads = 0

            def value(op):
                kind = op['$type'].split('EX_')[1].split(',')[0]
                if kind in ('StringConst', 'UnicodeStringConst', 'ByteConst'):
                    return op['Value']
                if kind == 'LocalVariable':
                    return self.locals[op['Variable']['New']['Path'][0]]
                if kind == 'CallMath':
                    name = import_path(op['StackNode'])[-1]
                    params = [value(p) for p in op['Parameters']]
                    if name == 'GetCurrentLanguage':
                        assert not params
                        self.language_reads += 1
                        return self.current_language
                    if name == 'EqualEqual_StriStri':
                        return params[0].casefold() == params[1].casefold()
                    if name == 'StartsWith':
                        assert params[2] == 0, 'Language tag matching must ignore case'
                        return params[0].casefold().startswith(params[1].casefold())
                    if name == 'BooleanOR':
                        return params[0] or params[1]
                    if name == 'Conv_StringToText':
                        assert len(params) == 1
                        return params[0]
                raise AssertionError(('Unexpected expression', kind))

            pc = 0
            for _ in range(len(ops)):
                op = ops[pc]
                kind = op['$type'].split('EX_')[1].split(',')[0]
                pc += size(op)
                if kind == 'Let':
                    self.locals[op['Variable']['Variable']['New']['Path'][0]] = value(op['Expression'])
                elif kind == 'JumpIfNot':
                    if not value(op['BooleanExpression']):
                        pc = op['CodeOffset']
                elif kind == 'Return':
                    text = value(op['ReturnExpression'])
                    assert self.language_reads == 1
                    return text
                else:
                    raise AssertionError(('Unexpected instruction', kind))
            raise AssertionError('Heading getter failed to return')

    # Expectations are independent of the builder's translation/tag table.
    cases = [
        ('en', 'EQUIPPED'), ('en-US', 'EQUIPPED'),
        ('zh-Hans', '已装备'), ('zh-Hans-CN', '已装备'), ('zh-CN', '已装备'),
        ('zh-SG', '已装备'), ('zh', '已装备'), ('ZH-hans', '已装备'),
        ('es', 'EQUIPADO'), ('es-ES', 'EQUIPADO'), ('es-419', 'EQUIPADO'), ('es-MX', 'EQUIPADO'),
        ('pt-BR', 'EQUIPADO'), ('pt-br', 'EQUIPADO'), ('pt', 'EQUIPADO'),
        ('de', 'AUSGERÜSTET'), ('de-DE', 'AUSGERÜSTET'), ('de-AT', 'AUSGERÜSTET'), ('DE-ch', 'AUSGERÜSTET'),
        ('ja', '装備中'), ('ja-JP', '装備中'),
        ('pl', 'WYPOSAŻONO'), ('pl-PL', 'WYPOSAŻONO'), ('PL-pl', 'WYPOSAŻONO'),
        ('ko', '장착 중'), ('ko-KR', '장착 중'), ('KO-kr', '장착 중'),
        ('ru', 'ЭКИПИРОВАНО'), ('ru-RU', 'ЭКИПИРОВАНО'), ('RU-ru', 'ЭКИПИРОВАНО'),
        ('zh-Hant', 'EQUIPPED'), ('zh-Hant-TW', 'EQUIPPED'), ('zh-TW', 'EQUIPPED'),
        ('zh-HK', 'EQUIPPED'), ('zh-MO', 'EQUIPPED'), ('pt-PT', 'EQUIPPED'),
        ('fr', 'EQUIPPED'),
        ('it', 'EQUIPPED'), ('cs', 'EQUIPPED'), ('hu', 'EQUIPPED'), ('tr', 'EQUIPPED'),
        ('', 'EQUIPPED'), ('unknown', 'EQUIPPED'), ('des', 'EQUIPPED'),
        ('esoteric', 'EQUIPPED'), ('zh-HansExtra', 'EQUIPPED'),
        ('plaster', 'EQUIPPED'), ('kor', 'EQUIPPED'), ('run', 'EQUIPPED'),
        # Language changes in the same widget must not cache the first result.
        ('de-DE', 'AUSGERÜSTET'), ('ja-JP', '装備中'), ('es-419', 'EQUIPADO'),
        ('pl-PL', 'WYPOSAŻONO'), ('ko-KR', '장착 중'), ('ru-RU', 'ЭКИПИРОВАНО'), ('en', 'EQUIPPED'),
    ]
    if variant == 'russian-heading':
        # Only English is redirected. Existing language choices and fallback
        # remain intact, and changing back to English restores Russian.
        cases = [(tag, 'ЭКИПИРОВАНО' if tag in ('en', 'en-US') else expected)
                 for tag, expected in cases]
        cases += [('en-GB', 'ЭКИПИРОВАНО'), ('EN-us', 'ЭКИПИРОВАНО'),
                  ('english', 'EQUIPPED'), ('enochian', 'EQUIPPED'),
                  ('pl-PL', 'WYPOSAŻONO'), ('en', 'ЭКИПИРОВАНО'),
                  ('ko-KR', '장착 중'), ('en-US', 'ЭКИПИРОВАНО')]
    vm = VM()
    for culture, expected in cases:
        vm.current_language = culture
        assert vm.evaluate() == expected, (private, culture, expected)
    # The static fallback remains safe if the widget is inspected before binding.
    assert getprop(a.export('IC_EquippedLabel'), 'Text')['CultureInvariantString'] == 'EQUIPPED'
    return len(cases)
