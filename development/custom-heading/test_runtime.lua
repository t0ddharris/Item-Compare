-- UE4SS boundary model. Executed by real Lua 5.4; never loaded into the game.
local source, config_source = ...
local total = 0
local BASE = "/Game/_Dawnwalker/UI/_Unified/GameHub/Inventory/Tooltip/"
local INVENTORY = "WBP_IC_InventoryTooltip"
local TRADE = "WBP_IC_TradeStorageTooltip"

local function boot(settings)
    settings = settings or {}
    local state = {queue = {}, loops = {}, hooks = {}, functions = {}, objects = {}, logs = {},
        game_thread = false, scans = 0, registrations = 0, writes = 0}
    local env = setmetatable({}, {__index = _G})
    env._G = env
    env.print = function(line) table.insert(state.logs, line) end
    env.require = function(name)
        assert(name == "config")
        if settings.config_error then error("Invalid configuration") end
        if settings.config_value ~= nil then return settings.config_value end
        return {Text = settings.text or "WYPOSAŻONO"}
    end
    env.FText = function(value)
        assert(state.game_thread, "FText created off the game thread")
        assert(type(value) == "string")
        return {value = value}
    end
    env.ExecuteInGameThread = function(callback)
        if state.fail_queue then error("Scheduler unavailable") end
        table.insert(state.queue, callback)
    end
    env.LoopAsync = function(delay, callback)
        assert(delay == 1000)
        table.insert(state.loops, callback)
    end
    env.FindAllOf = function(name)
        assert(state.game_thread, "Object lookup off the game thread")
        assert(name == INVENTORY .. "_C" or name == TRADE .. "_C")
        state.scans = state.scans + 1
        if state.fail_find == name then error("Lookup unavailable") end
        return state.objects[name]
    end
    env.StaticFindObject = function(path)
        assert(state.game_thread)
        if path == "/Script/Engine.Default__KismetTextLibrary" then
            state.library_lookups = (state.library_lookups or 0) + 1
            if state.no_library then return nil end
            return {
                IsValid = function() return not state.invalid_library end,
                Conv_StringToText = function(_, value)
                    assert(state.game_thread)
                    assert(type(value) == "string")
                    if state.fail_conversion then error("Text marshaling unavailable") end
                    if state.nil_conversion then return nil end
                    state.conversions = (state.conversions or 0) + 1
                    return {value = value}
                end,
            }
        end
        return state.functions[path]
    end
    env.RegisterHook = function(path, callback)
        assert(state.game_thread)
        state.registrations = state.registrations + 1
        if state.fail_hook then error("Hook unavailable") end
        assert(state.functions[path], "Hooked an unloaded function")
        state.hooks[path] = callback
        return 100, 101
    end
    if settings.no_hooks then
        env.StaticFindObject = false
        env.RegisterHook = false
    end
    if settings.missing_api then env[settings.missing_api] = false end

    function state.drain()
        local pending = state.queue
        state.queue = {}
        state.game_thread = true
        for _, callback in ipairs(pending) do callback() end
        state.game_thread = false
    end
    function state.tick()
        for _, loop in ipairs(state.loops) do assert(loop() == false) end
        state.drain()
    end
    function state.object(name, class, flags)
        local obj = {name = name, class = class, flags = flags or 0, valid = true}
        function obj:IsValid() return self.valid end
        function obj:IsA(path) assert(state.game_thread); return self.class == path end
        function obj:HasAnyFlags(mask) assert(state.game_thread); return (self.flags & mask) ~= 0 end
        function obj:GetFName()
            assert(state.game_thread)
            return {ToString = function() return self.name end}
        end
        return obj
    end
    function state.tooltip(asset, options)
        options = options or {}
        local path = BASE .. asset .. "." .. asset .. "_C"
        local tooltip = state.object("LiveTooltip", path, options.flags)
        local label = state.object(options.label_name or "IC_EquippedLabel",
            options.label_class or "/Script/UMG.TextBlock", options.label_flags)
        label.text = options.initial_text or "EQUIPPED"
        label.bound = true
        label.writes = 0
        function label:SetText(value)
            assert(state.game_thread, "UI write off the game thread")
            assert(self.valid)
            if self.fail_set then error("Text setter unavailable") end
            self.text, self.bound = value.value, false
            self.writes = self.writes + 1
            state.writes = state.writes + 1
        end
        local other = state.object("ItemName", "/Script/UMG.TextBlock")
        other.text = "Original item name"
        function other:SetText() error("Changed unrelated text!") end
        local stack = state.object("IC_Stack", "/Script/UMG.VerticalBox")
        stack.children = options.reordered and {other, label} or {label, other}
        function stack:GetChildrenCount() assert(state.game_thread); return #self.children end
        function stack:GetChildAt(index) assert(state.game_thread); return self.children[index + 1] end
        if not options.uninitialized then tooltip.IC_Stack = stack end
        -- Explicitly no IC_EquippedLabel class member, as in main 1.1.2.
        tooltip.label, tooltip.stack, tooltip.other = label, stack, other
        if not options.unlisted then
            local list = state.objects[asset .. "_C"] or {}
            state.objects[asset .. "_C"] = list
            table.insert(list, tooltip)
        end
        return tooltip
    end
    function state.load_function(asset, address)
        local path = BASE .. asset .. "." .. asset .. "_C:IC_UpdateComparison"
        state.functions[path] = {IsValid = function() return true end,
            GetAddress = function() return address or 1000 end}
        return path
    end
    function state.call_hook(path, tooltip)
        local alive = true
        local context = {get = function()
            assert(alive, "Read expired RemoteUnrealParam after the hook returned")
            return tooltip
        end}
        assert(state.hooks[path])
        assert(state.hooks[path](context) == nil, "Overrode the original function result")
        alive = false
    end
    assert(load(source, "@ItemCompareCustomHeading/Scripts/main.lua", "t", env))()
    return state
end

local function test(name, callback)
    local ok, err = pcall(callback)
    assert(ok, name .. ": " .. tostring(err))
    total = total + 1
end

test("shipped configuration parses", function()
    local config = assert(load(config_source, "@config.lua", "t", {}))()
    assert(config.Text == "EQUIPPED")
end)
for _, text in ipairs({"EQUIPPED", "WYPOSAŻONO", "장착 중", "ЭКИПИРОВАНО", "AUSGERÜSTET",
        "EQUIPADO", "装備中", "已装备", "✓", "🗹", "مُجهَّز", 'A "quoted" heading'}) do
    test("UTF-8 override " .. text, function()
        local s = boot({text = text})
        local inventory, trade = s.tooltip(INVENTORY), s.tooltip(TRADE)
        s.drain()
        for _, tooltip in ipairs({inventory, trade}) do
            assert(tooltip.label.text == text and not tooltip.label.bound, table.concat(s.logs, " "))
            assert(tooltip.other.text == "Original item name")
            assert(tooltip.IC_EquippedLabel == nil)
        end
    end)
end
for _, settings in ipairs({{config_error = true}, {config_value = true}, {config_value = {}},
        {config_value = {Text = 12}}, {text = ""}, {text = "   "}, {text = "a\nb"},
        {text = "a\0b"}, {text = "a\tb"}, {text = string.char(255)}}) do
    test("bad configuration has no effects", function()
        local s = boot(settings)
        assert(#s.queue == 0 and #s.loops == 0 and s.writes == 0)
        assert(#s.logs == 1)
    end)
end
for _, api in ipairs({"FindAllOf", "LoopAsync", "ExecuteInGameThread"}) do
    test("missing API stops clearly", function()
        local s = boot({missing_api = api})
        assert(#s.queue == 0 and #s.loops == 0 and #s.logs == 1)
    end)
end
test("main mod absent or late", function()
    local s = boot()
    for i = 1, 5 do s.tick() end
    assert(s.writes == 0 and #s.logs == 1)
    local tooltip = s.tooltip(INVENTORY)
    s.tick()
    assert(tooltip.label.text == "WYPOSAŻONO")
end)
test("unfinished widget retried", function()
    local s = boot()
    local tooltip = s.tooltip(INVENTORY, {uninitialized = true})
    s.drain()
    assert(s.writes == 0)
    tooltip.IC_Stack = tooltip.stack
    s.tick()
    assert(s.writes == 1)
end)
test("child order can change", function()
    local s = boot()
    local tooltip = s.tooltip(INVENTORY, {reordered = true})
    s.drain()
    assert(tooltip.label.text == "WYPOSAŻONO")
end)
for _, options in ipairs({{flags = 0x10}, {flags = 0x20}, {label_flags = 0x20},
        {label_name = "OtherText"}, {label_class = "/Script/UMG.Button"}}) do
    test("unrelated and template objects untouched", function()
        local s = boot()
        local tooltip = s.tooltip(INVENTORY, options)
        s.drain()
        assert(tooltip.label.text == "EQUIPPED" and s.writes == 0)
    end)
end
test("same short class name in another package rejected", function()
    local s = boot()
    local tooltip = s.tooltip(INVENTORY)
    tooltip.class = "/Game/OtherMod/" .. INVENTORY .. "." .. INVENTORY .. "_C"
    s.drain()
    assert(s.writes == 0)
end)
test("invalid objects and labels ignored", function()
    local s = boot()
    local a, b = s.tooltip(INVENTORY), s.tooltip(TRADE)
    a.valid, b.label.valid = false, false
    s.drain()
    assert(s.writes == 0)
end)
test("destroyed and recreated tooltip", function()
    local s = boot()
    local first = s.tooltip(INVENTORY)
    s.drain()
    first.valid = false
    local second = s.tooltip(INVENTORY)
    s.tick()
    assert(first.label.writes == 1 and second.label.writes == 1)
end)
test("language change or competing text write recovered", function()
    local s = boot()
    local tooltip = s.tooltip(INVENTORY)
    s.drain()
    tooltip.label.text, tooltip.label.bound = "EQUIPPED", true
    s.tick()
    assert(tooltip.label.text == "WYPOSAŻONO" and not tooltip.label.bound)
end)
test("same initial text still clears binding", function()
    local s = boot({text = "EQUIPPED"})
    local tooltip = s.tooltip(INVENTORY)
    s.drain()
    assert(not tooltip.label.bound and tooltip.label.writes == 1)
end)
test("paused game thread coalesces periodic requests", function()
    local s = boot()
    for i = 1, 100 do s.loops[1]() end
    assert(#s.queue == 1 and s.scans == 0 and s.writes == 0)
    s.drain()
    assert(s.scans == 2)
end)
test("functions load late; register only once", function()
    local s = boot()
    s.drain()
    assert(s.registrations == 0)
    s.load_function(INVENTORY)
    s.tick(); s.tick()
    assert(s.registrations == 1)
end)
test("hook handles new instances and unwraps context before deferral", function()
    local s = boot()
    local path = s.load_function(INVENTORY)
    s.drain()
    local tooltip = s.tooltip(INVENTORY, {unlisted = true})
    s.call_hook(path, tooltip)
    assert(tooltip.label.text == "EQUIPPED")
    s.drain()
    assert(tooltip.label.text == "WYPOSAŻONO")
end)
test("hook target destroyed before queued update", function()
    local s = boot()
    local path = s.load_function(TRADE)
    s.drain()
    local tooltip = s.tooltip(TRADE, {unlisted = true})
    s.call_hook(path, tooltip)
    tooltip.valid = false
    s.drain()
    assert(s.writes == 0)
end)
test("hook unavailable uses discovery without repeated registration", function()
    local s = boot()
    s.fail_hook = true
    s.load_function(INVENTORY)
    local tooltip = s.tooltip(INVENTORY)
    s.drain(); s.tick()
    assert(s.registrations == 1 and tooltip.label.text == "WYPOSAŻONO")
end)
test("no hook APIs still works", function()
    local s = boot({no_hooks = true})
    local tooltip = s.tooltip(INVENTORY)
    s.drain()
    assert(tooltip.label.text == "WYPOSAŻONO")
end)
test("function replacement registered", function()
    local s = boot()
    s.load_function(INVENTORY, 1000)
    s.drain()
    s.load_function(INVENTORY, 2000)
    s.tick()
    assert(s.registrations == 2)
end)
test("one broken tooltip does not block the next", function()
    local s = boot()
    local a, b = s.tooltip(INVENTORY), s.tooltip(INVENTORY)
    a.label.fail_set = true
    s.drain(); s.tick()
    assert(b.label.text == "WYPOSAŻONO")
    assert(#s.logs == 3, "Repeated error spam")
end)
test("one failed class lookup does not block the other", function()
    local s = boot()
    s.fail_find = INVENTORY .. "_C"
    local tooltip = s.tooltip(TRADE)
    s.drain()
    assert(tooltip.label.text == "WYPOSAŻONO")
end)
test("queue failure recovers", function()
    local s = boot()
    s.drain()
    s.fail_queue = true
    s.loops[1]()
    assert(#s.queue == 0)
    s.fail_queue = false
    local tooltip = s.tooltip(INVENTORY)
    s.tick()
    assert(tooltip.label.text == "WYPOSAŻONO")
end)
for _, value in ipairs({"CUSTOM", "WYPOSAŻONO", "장착 중", "ЭКИПИРОВАНО", "装備中"}) do
    test("missing FText uses engine conversion: " .. value, function()
        local s = boot({missing_api = "FText", text = value})
        local a, b = s.tooltip(INVENTORY), s.tooltip(TRADE)
        s.drain()
        assert(a.label.text == value and b.label.text == value)
        assert(not a.label.bound and not b.label.bound and s.conversions == 2)
        a.label.text = "EQUIPPED"
        s.tick()
        assert(a.label.text == value)
    end)
end
test("native constructor does not require text library", function()
    local s = boot(); s.no_library = true
    local a = s.tooltip(INVENTORY); s.drain()
    assert(a.label.text == "WYPOSAŻONO" and s.library_lookups == nil)
end)
for _, failure in ipairs({"no_library", "invalid_library", "fail_conversion", "nil_conversion"}) do
    test("text fallback failure retries: " .. failure, function()
        local s = boot({missing_api = "FText"}); s[failure] = true
        local a = s.tooltip(INVENTORY)
        s.drain(); s.tick()
        assert(a.label.text == "EQUIPPED" and s.writes == 0)
        assert(#s.logs == 2, "Fallback error repeated every sweep")
        s[failure] = false; s.tick()
        assert(a.label.text == "WYPOSAŻONO")
    end)
end
test("no constructor and no lookup leaves stock heading", function()
    local s = boot({missing_api = "FText", no_hooks = true})
    local a = s.tooltip(INVENTORY); s.drain(); s.tick()
    assert(a.label.text == "EQUIPPED" and s.writes == 0 and #s.logs == 2)
end)
return total
