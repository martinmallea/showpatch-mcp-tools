-- mcp_state_bridge.lua — Plugin residente en MA3 para push de estado vía OSC.
-- Instalación: Import en Plugin Pool, Trigger: Startup.

local PLUGIN_NAME = "mcp_state_bridge"
local TARGET_IP = "192.168.0.100"
local TARGET_PORT = 8001

local function now_ms()
    return math.floor(GetSystemTime() * 1000)
end

local function send_state_event(object_type, attribute, value, fixture_id)
    local msg = string.format("EVENT|%d|%s|%s|%s|%s",
        now_ms(), object_type, attribute, tostring(value), tostring(fixture_id))
    CmdIndirect(string.format(
        'SendOSC "%s:%d" "/mcp/state" "%s"', TARGET_IP, TARGET_PORT, msg))
end

local function onProgrammerChange()
    send_state_event("programmer", "any", "changed", "0")
end

return function()
    local ok = pcall(function()
        HookObjectChange("Programmer", onProgrammerChange)
    end)
    if not ok then
        Printf("[" .. PLUGIN_NAME .. "] hooks no disponibles; polling delegado.")
    else
        Printf("[" .. PLUGIN_NAME .. "] hooks registrados.")
    end
end
