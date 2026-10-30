-- Item Compare Custom Heading 1.0.1. Optional UE4SS companion.
-- Only live Item Compare heading text is changed; no game files are written.
local TAG = "[ItemCompareCustomHeading] "
local function log(message)
    print(TAG .. message .. "\n")
end

local loaded, config = pcall(require, "config")
if not loaded or type(config) ~= "table" or type(config.Text) ~= "string" then
    log("Could not read config.lua. Set Text to a quoted string, then restart the game.")
    return
end
local text = config.Text
-- ASCII control bytes only: locale-sensitive Lua %c can misclassify UTF-8
-- continuation bytes on Windows (for example, in Cyrillic text).
if text:match("^[ \t\r\n\v\f]*$") or text:find("[%z\1-\31\127]") or not utf8.len(text) then
    log("Text must be one non-empty line of UTF-8 text. Check config.lua and restart the game.")
    return
end
for _, name in ipairs({"FindAllOf", "LoopAsync", "ExecuteInGameThread"}) do
    if type(_G[name]) ~= "function" then
        log("Missing UE4SS function " .. name .. ". Use a UE4SS build compatible with Dawnwalker.")
        return
    end
end

local BASE = "/Game/_Dawnwalker/UI/_Unified/GameHub/Inventory/Tooltip/"
local targets = {
    {name = "WBP_IC_InventoryTooltip_C", asset = "WBP_IC_InventoryTooltip"},
    {name = "WBP_IC_TradeStorageTooltip_C", asset = "WBP_IC_TradeStorageTooltip"},
}
for _, target in ipairs(targets) do
    target.path = BASE .. target.asset .. "." .. target.name
    target.hook = target.path .. ":IC_UpdateComparison"
end

local warned = {}
local function warn_once(key, message)
    if not warned[key] then
        warned[key] = true
        log(message)
    end
end
local function valid(object)
    return object ~= nil and object:IsValid()
end

-- Some Dawnwalker loaders omit the Lua FText constructor. Let Unreal create
-- the value through its reflected function instead. Resolve on the game
-- thread for each write; do not retain a borrowed text result between sweeps.
local function heading_text()
    if type(FText) == "function" then return FText(text) end
    if type(StaticFindObject) ~= "function" then
        error("This UE4SS build has neither FText nor StaticFindObject for the text fallback.")
    end
    local library = StaticFindObject("/Script/Engine.Default__KismetTextLibrary")
    if not valid(library) then error("Unreal text library is unavailable; will retry.") end
    local converted = library:Conv_StringToText(text)
    if converted == nil then error("UE4SS did not return converted text; the heading was left unchanged.") end
    return converted
end

-- Called only on the game thread, after validating the owning tooltip.
-- IC_Stack is an existing member in the main releases. Looking at its children
-- also works in builds where IC_EquippedLabel is not itself a class member.
local function apply(tooltip, target)
    if not valid(tooltip) or not tooltip:IsA(target.path) then return end
    -- RF_ClassDefaultObject | RF_ArchetypeObject: never edit asset templates.
    if tooltip:HasAnyFlags(0x30) then return end
    local stack = tooltip.IC_Stack
    if not valid(stack) then return end -- Widget initialization is not finished.
    local count = stack:GetChildrenCount()
    for index = 0, count - 1 do
        local label = stack:GetChildAt(index)
        if valid(label) and label:GetFName():ToString() == "IC_EquippedLabel"
                and label:IsA("/Script/UMG.TextBlock")
                and not label:HasAnyFlags(0x30) then
            -- SetText also clears any automatic Text binding, so a manual
            -- choice remains authoritative after the game's language changes.
            label:SetText(heading_text())
            if not target.applied then
                target.applied = true
                log("Custom heading applied to " .. target.name .. ".")
            end
            return
        end
    end
end

local function try_apply(tooltip, target)
    local ok, err = pcall(apply, tooltip, target)
    if not ok then
        warn_once(target.name, "Could not update " .. target.name .. ": " .. tostring(err))
    end
end

-- Refresh callbacks avoid waiting for the next discovery sweep on normal
-- hovers. These are optional: discovery still works on builds without hooks.
local function attach_hook(target)
    if type(StaticFindObject) ~= "function" or type(RegisterHook) ~= "function" then return end
    local fn = StaticFindObject(target.hook)
    if not valid(fn) then return end -- Assets can load long after this script.
    local address = fn:GetAddress()
    if target.hook_address == address then return end
    target.hook_address = address
    local ok, err = pcall(RegisterHook, target.hook, function(context)
        -- Do not return anything: preserve the original function's result.
        -- RemoteUnrealParam belongs to this callback; unwrap before deferring.
        local unwrapped, tooltip = pcall(function() return context:get() end)
        if not unwrapped then return end
        local queued, problem = pcall(ExecuteInGameThread, function()
            try_apply(tooltip, target)
        end)
        if not queued then
            warn_once("hook_queue", "Could not queue a heading update: " .. tostring(problem))
        end
    end)
    if not ok then
        warn_once(target.hook, "Using periodic heading updates for " .. target.name .. ": " .. tostring(err))
    end
end

local function sweep()
    for _, target in ipairs(targets) do
        local hooked, hook_error = pcall(attach_hook, target)
        if not hooked then warn_once(target.hook, "Hook lookup failed: " .. tostring(hook_error)) end
        local found, instances = pcall(FindAllOf, target.name)
        if found then
            for _, tooltip in ipairs(instances or {}) do try_apply(tooltip, target) end
        else
            warn_once("find_" .. target.name, "Tooltip lookup failed: " .. tostring(instances))
        end
    end
end

-- Discover existing and newly recreated tooltips, retry unfinished widgets,
-- and recover if another refresh restores the main heading. Only two private
-- tooltip classes are queried. Do not retain widget references across scans.
-- Coalesce async requests while the game thread is paused or busy.
local in_flight = false
local function request_sweep()
    if in_flight then return end
    in_flight = true
    local queued, err = pcall(ExecuteInGameThread, function()
        local ok, problem = pcall(sweep)
        in_flight = false
        if not ok then warn_once("sweep", "Heading update failed: " .. tostring(problem)) end
    end)
    if not queued then
        in_flight = false
        warn_once("queue", "Could not queue heading discovery: " .. tostring(err))
    end
end

log("Loaded. Custom text comes from Scripts/config.lua; restart the game after edits.")
request_sweep()
LoopAsync(1000, function()
    request_sweep()
    return false
end)
