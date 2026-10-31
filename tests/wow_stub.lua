-- Synthetic stand-in for the slice of the World of Warcraft interface that WoWCompanionProbe uses.
-- Every value in here is invented. tests/addon_runtime.py loads it under Lua 5.1, the language the
-- game runs addons in, so numbers are doubles and there is no integer type. It is test support only
-- and is never part of the addon or the helper.

Stub = {
  env = {},       -- what the invented game reports; tests replace it for each state they want
  printed = {},   -- lines the addon sent to the chat frame
  frames = {},    -- every frame the addon created, in order
  named = {},     -- the same frames by name
  timers = {},    -- pending C_Timer.After callbacks
  clock = 0,      -- virtual seconds
  copied = nil,   -- what CopyToClipboard last received
}

-- A value the client marks secret. Handing it to issecretvalue() is the one allowed use: anything
-- else raises, which is how the game treats it.
local function refuse() error("a secret value was used", 2) end
local SECRET = setmetatable({}, {
  __index = refuse, __newindex = refuse, __call = refuse, __concat = refuse, __len = refuse,
  __unm = refuse, __add = refuse, __sub = refuse, __mul = refuse, __div = refuse, __mod = refuse,
  __pow = refuse, __lt = refuse, __le = refuse, __tostring = refuse,
})
Stub.SECRET = SECRET
function issecretvalue(value) return rawequal(value, SECRET) end

-- Repeatable randomness (Park-Miller). Doubles hold the products exactly.
local seed = 12345
math.random = function(low, high)
  seed = (seed * 16807) % 2147483647
  if low == nil then return seed / 2147483647 end
  return low + seed % (high - low + 1)
end

function print(...)
  local parts = {}
  for index = 1, select("#", ...) do parts[index] = tostring((select(index, ...))) end
  Stub.printed[#Stub.printed + 1] = table.concat(parts, " ")
end

-- Virtual time: nothing runs until a test advances the clock.
C_Timer = {
  After = function(seconds, fn)
    Stub.timers[#Stub.timers + 1] = { at = Stub.clock + seconds, fn = fn }
  end,
}
function Stub.advance(seconds)
  local target = Stub.clock + seconds
  while true do
    local pick
    for index, timer in ipairs(Stub.timers) do
      if timer.at <= target and (not pick or timer.at < Stub.timers[pick].at) then pick = index end
    end
    if not pick then break end
    local timer = table.remove(Stub.timers, pick)
    Stub.clock = timer.at
    timer.fn()
  end
  Stub.clock = target
end

-- Widgets. Methods are capitalised, as in the game, and any method nobody modelled is a recorded
-- no-op; a lower-case name that was never set is nil, so addon fields behave like table fields.
-- The stub's own state uses underscore names so it cannot collide with a field the addon sets.
local Widget = {}
Widget.__index = function(self, key)
  local method = Widget[key]
  if method ~= nil then return method end
  if type(key) == "string" and key:find("^%u") then
    return function(me) me._calls[#me._calls + 1] = key end
  end
end

local function widget(kind, name, parent)
  return setmetatable({ _kind = kind, _name = name, _parent = parent, _calls = {}, _children = {},
                        _scripts = {}, _shown = true }, Widget)
end

function Widget:CreateTexture(name, layer)
  local texture = widget("Texture", name, self)
  texture._layer = layer
  self._children[#self._children + 1] = texture
  return texture
end
function Widget:CreateFontString()
  local text = widget("FontString", nil, self)
  self._children[#self._children + 1] = text
  return text
end
function Widget:SetScript(event, fn) self._scripts[event] = fn end
function Widget:SetPoint(point, relative, relativePoint, x, y)
  self._point = { point, relative, relativePoint, x or 0, y or 0 }
end
function Widget:ClearAllPoints() self._point = nil end
function Widget:SetSize(width, height) self._w, self._h = width, height end
function Widget:GetHeight() return self._h or 0 end
function Widget:SetColorTexture(r, g, b, a) self._color = { r, g, b, a } end
function Widget:Show() self._shown = true end
function Widget:Hide() self._shown = false end
function Widget:IsShown() return self._shown end
function Widget:GetText() return self._text or "" end
function Widget:SetText(text)
  self._text = text
  local changed = self._scripts.OnTextChanged
  if self._kind == "EditBox" and changed then changed(self, false) end
end

function CreateFrame(kind, name, parent, template)
  if template and Stub.env.noTemplates then error("unknown frame template", 2) end
  local frame = widget(kind, name, parent)
  Stub.frames[#Stub.frames + 1] = frame
  if name then Stub.named[name] = frame end
  return frame
end

UIParent = widget("Frame", "UIParent")
UIParent.GetHeight = function() return Stub.env.uiHeight or 768 end
SlashCmdList = {}

-- A person typing into an edit box.
function Stub.type(box, text)
  box._text = text
  local changed = box._scripts.OnTextChanged
  if changed then changed(box, true) end
end

-- The white rectangles of the strip as the screen would show them, in whole physical pixels, as
-- left, top, width, height runs in one flat list. Returns the frame width and height first.
function Stub.stripPixels()
  local frame = Stub.named.WoWCompanionProbeStrip
  if not frame then return nil end
  local pixel = (Stub.env.uiHeight or 768) / (Stub.env.physicalHeight or 1080)
  local function snap(value) return math.floor(value / pixel + 0.5) end
  local flat = {}
  for _, texture in ipairs(frame._children) do
    if texture._kind == "Texture" and texture._layer == "ARTWORK" and texture._shown and texture._point then
      local left, top = snap(texture._point[4]), snap(-texture._point[5])
      flat[#flat + 1] = left
      flat[#flat + 1] = top
      flat[#flat + 1] = snap(texture._point[4] + texture._w) - left
      flat[#flat + 1] = snap(-texture._point[5] + texture._h) - top
    end
  end
  return snap(frame._w), snap(frame._h), flat
end

-- The invented game. A name in Stub.env.secret answers with a secret value instead.
local function answer(name, ...)
  local secret = Stub.env.secret
  if secret and secret[name] then return SECRET end
  return ...
end

function GetBuildInfo()
  if Stub.env.noBuild then return end
  return "1.2.3", "12345", "Jan 01 2030", Stub.env.interface or 16001
end
function GetServerTime() return answer("GetServerTime", Stub.env.now or 1790000000) end
function GetPhysicalScreenSize() return Stub.env.physicalWidth or 1920, Stub.env.physicalHeight or 1080 end
function UnitLevel() return answer("UnitLevel", Stub.env.level or 12) end
function UnitClass()
  if Stub.env.secret and Stub.env.secret.UnitClass then return SECRET, SECRET, SECRET end
  return "Warrior", "WARRIOR", 1
end
function UnitGUID() return answer("UnitGUID", Stub.env.guid or "Player-0000-00000001") end
function GetRealZoneText() return answer("GetRealZoneText", Stub.env.zone or "Testvale") end
function GetSubZoneText() return answer("GetSubZoneText", Stub.env.sub or "Example Crossing") end

C_Map = {
  GetBestMapForUnit = function() return answer("GetBestMapForUnit", Stub.env.map or 9001) end,
}
C_SuperTrack = {
  GetSuperTrackedQuestID = function() return answer("GetSuperTrackedQuestID", Stub.env.tracked or 0) end,
}
C_QuestLog = {
  GetNumQuestWatches = function() return answer("GetNumQuestWatches", Stub.env.watches or 0) end,
  GetQuestIDForQuestWatchIndex = function() return answer("GetQuestIDForQuestWatchIndex", Stub.env.watched) end,
  GetNumQuestLogEntries = function()
    return answer("GetNumQuestLogEntries", Stub.env.log and #Stub.env.log or 0)
  end,
  GetInfo = function(index) return answer("GetInfo", Stub.env.log and Stub.env.log[index]) end,
  GetTitleForQuestID = function() return answer("GetTitleForQuestID", Stub.env.title or "Synthetic Delivery") end,
  IsComplete = function() return answer("IsComplete", Stub.env.complete or false) end,
  GetQuestObjectives = function() return answer("GetQuestObjectives", Stub.env.objectives or {}) end,
}

function CopyToClipboard(text)
  if Stub.env.copyBlocked then error("CopyToClipboard is restricted", 2) end
  Stub.copied = text
end

-- Loads the addon the way the client does, passing its name and a private table, and records every
-- global it reads or writes so a test can say which parts of the interface it touched.
Stub.globalsRead, Stub.globalsWritten = {}, {}
local watched = setmetatable({}, {
  __index = function(_, key) Stub.globalsRead[key] = true return _G[key] end,
  __newindex = function(_, key, value) Stub.globalsWritten[key] = true rawset(_G, key, value) end,
})
function Stub.load(source, ns)
  local chunk = assert(loadstring(source, "=WoWCompanionProbe.lua"))
  setfenv(chunk, watched)
  chunk("WoWCompanionProbe", ns)
end
