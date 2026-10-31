-- WoW Companion Probe: an opt-in measuring tool for the helper's context channel.
-- It does nothing until asked. /wfhprobe strip draws a black and white pattern that encodes a small
-- packet about what the game is showing, /wfhprobe copy shows the same packet as text to copy with
-- Ctrl+C, and /wfhprobe status reports which interface features this client has. The helper's
-- context-probe command then reads the result back, so each way of getting data out of the game
-- can be measured on a real client.
-- Read-only toward the game. It never casts, targets, moves, chats, accepts, or changes a setting,
-- registers no events, and its only saved data is a random salt used to hide the character id.
-- The packet format is defined by wow_helper/context/envelope.py and strip.py; keep them in step.

local addonName, ns = ...
ns = ns or {}

local VERSION = "0.1.0" -- keep equal to the .toc Version line
local PREFIX = "WFHC1:"
local COLUMNS = 160
local QUIET = 2
local MAX_OBJECTIVES = 8
local TITLE_CHARS, OBJECTIVE_CHARS = 60, 80
local SHOW_SECONDS = 15
local NULL = {}
ns.NULL, ns.VERSION, ns.PREFIX = NULL, VERSION, PREFIX

-- The field order the helper expects. wow_helper/context/envelope.py holds the same lists.
local ORDER = {
  root = { "v", "kind", "sid", "seq", "at", "build", "who", "where", "quest", "scope", "missing" },
  build = { "version", "build", "interface" },
  who = { "ref", "level", "class" },
  where = { "zone", "sub", "map" },
  quest = { "id", "pick", "title", "complete", "objectives" },
  objective = { "text", "have", "need", "done" },
  scope = { "quests" },
}
local CHILD = {
  root = { build = "build", who = "who", where = "where", quest = "quest", scope = "scope" },
  quest = { objectives = "objective" },
}
local LISTS = { objectives = true, missing = true }
local MISSING_NAMES = {
  "who", "who.ref", "who.level", "who.class",
  "where", "where.zone", "where.sub", "where.map",
  "quest", "quest.title", "quest.complete", "quest.objectives",
}
ns.ORDER, ns.MISSING_NAMES = ORDER, MISSING_NAMES

-- Bit operations: the game's bit library when present, plain arithmetic otherwise.
local function slowXor(a, b)
  local result, place = 0, 1
  for _ = 1, 16 do
    local x, y = a % 2, b % 2
    if x ~= y then result = result + place end
    a, b, place = (a - x) / 2, (b - y) / 2, place * 2
  end
  return result
end
local xor = (type(bit) == "table" and bit.bxor) or slowXor
ns.slowXor = slowXor

-- CRC-16/CCITT-FALSE, polynomial 0x1021, start value 0xFFFF.
local crcTable
local function crc16(bytes, first, last)
  if not crcTable then
    crcTable = {}
    for index = 0, 255 do
      local value = index * 256
      for _ = 1, 8 do
        if value >= 32768 then
          value = xor((value * 2) % 65536, 4129)
        else
          value = (value * 2) % 65536
        end
      end
      crcTable[index] = value
    end
  end
  local crc = 65535
  for position = first, last do
    local high = math.floor(crc / 256)
    crc = xor((crc % 256) * 256, crcTable[xor(high, bytes[position])])
  end
  return crc
end
ns.crc16 = crc16

-- Pattern classes like %c and %s follow the C library's locale and can match bytes above 127, which
-- would cut a valid UTF-8 character in two, so text handling below names its byte ranges instead.
-- Text from the game is cleaned before it goes in a packet. The helper cleans it again on receipt
-- (and names the fields it had to change), so this is the first of two passes, not the only one.
local function utf8Clean(text)
  if not text:find("[\128-\255]") then return text end
  local out, index, length = {}, 1, #text
  while index <= length do
    local lead = text:byte(index)
    if lead < 128 then
      out[#out + 1] = string.char(lead)
      index = index + 1
    else
      local size, low, high = 0, 128, 191
      if lead >= 194 and lead <= 223 then size = 2
      elseif lead == 224 then size, low = 3, 160
      elseif (lead >= 225 and lead <= 236) or lead == 238 or lead == 239 then size = 3
      elseif lead == 237 then size, high = 3, 159
      elseif lead == 240 then size, low = 4, 144
      elseif lead >= 241 and lead <= 243 then size = 4
      elseif lead == 244 then size, high = 4, 143 end
      local good = size > 0
      if good then
        local second = text:byte(index + 1)
        if not second or second < low or second > high then good = false end
        for offset = 2, size - 1 do
          local following = text:byte(index + offset)
          if not following or following < 128 or following > 191 then good = false end
        end
      end
      if good then
        out[#out + 1] = text:sub(index, index + size - 1)
        index = index + size
      else
        index = index + 1
      end
    end
  end
  return table.concat(out)
end

local function capChars(text, limit)
  local count = 0
  for index = 1, #text do
    local byte = text:byte(index)
    if byte < 128 or byte >= 192 then
      count = count + 1
      if count > limit then return text:sub(1, index - 1) end
    end
  end
  return text
end

local function clean(value, limit)
  if type(value) ~= "string" then return nil end
  local text = value
  text = text:gsub("|c%x%x%x%x%x%x%x%x", "")
  text = text:gsub("|cn[^:|]*:", "")
  text = text:gsub("|r", "")
  text = text:gsub("|H[^|]*|h([^\r\n]-)|h", "%1")
  text = text:gsub("|T[^|]*|t", "")
  text = text:gsub("|A[^|]*|a", "")
  text = text:gsub("|", "")
  text = text:gsub("[%z\1-\31\127]", " ")
  text = utf8Clean(text)
  text = text:gsub(" +", " ")
  text = text:match("^ *(.-) *$")
  return (capChars(text, limit):match("^ *(.-) *$"))
end
ns.clean = clean

-- JSON in the helper's exact layout: schema key order, no spaces, "|" and controls as \u escapes.
local function jsonString(text)
  return '"' .. text:gsub('[\1-\31"\\|]', function(char)
    if char == '"' then return '\\"' end
    if char == "\\" then return "\\\\" end
    return string.format("\\u%04x", char:byte())
  end) .. '"'
end

local function jsonWrite(value, kind)
  if value == nil or value == NULL then return "null" end
  local kindOf = type(value)
  if kindOf == "boolean" then return value and "true" or "false" end
  if kindOf == "number" then return string.format("%.0f", value) end
  if kindOf == "string" then return jsonString(value) end
  local parts = {}
  local order = ORDER[kind]
  for _, key in ipairs(order) do
    local child = CHILD[kind] and CHILD[kind][key]
    local item = value[key]
    if LISTS[key] and item ~= nil and item ~= NULL then
      local list = {}
      for index = 1, #item do list[index] = jsonWrite(item[index], child) end
      parts[#parts + 1] = jsonString(key) .. ":[" .. table.concat(list, ",") .. "]"
    else
      parts[#parts + 1] = jsonString(key) .. ":" .. jsonWrite(item, child)
    end
  end
  return "{" .. table.concat(parts, ",") .. "}"
end
ns.json = function(packet) return jsonWrite(packet, "root") end

-- Reading game state. Anything can be missing or restricted; a value the client marks secret is
-- never touched, only reported as unreadable.
local function open(value)
  if issecretvalue and issecretvalue(value) then return nil end
  return value
end

local function read(fn, ...)
  if type(fn) ~= "function" then return false end
  local ok, a, b, c, d = pcall(fn, ...)
  if not ok then return false end
  if issecretvalue and (issecretvalue(a) or issecretvalue(b) or issecretvalue(c) or issecretvalue(d)) then return false end
  return true, a, b, c, d
end

local function whole(value, low, high)
  if type(value) ~= "number" or value ~= value or value < low or value > high then return nil end
  return math.floor(value)
end

local function hexDigits(count)
  local out = {}
  for index = 1, count do out[index] = string.format("%x", math.random(0, 15)) end
  return table.concat(out)
end

local function hash(text)
  local a, b = 7, 11
  for index = 1, #text do
    local byte = text:byte(index)
    a = (a * 131 + byte) % 2147483629
    b = (b * 257 + byte + index) % 2147483587
  end
  return string.format("%08x%08x", a, b)
end
ns.hash = hash

local function salt()
  if type(WoWCompanionProbeDB) ~= "table" then WoWCompanionProbeDB = {} end
  if type(WoWCompanionProbeDB.salt) ~= "string" or #WoWCompanionProbeDB.salt ~= 16 then
    WoWCompanionProbeDB.salt = hexDigits(16)
  end
  return WoWCompanionProbeDB.salt
end

local function pickQuest()
  local readable = false
  local ok, id = read(C_SuperTrack and C_SuperTrack.GetSuperTrackedQuestID)
  if ok then readable = true end
  if ok and type(id) == "number" and id > 0 then return id, "tracked", true end
  local log = C_QuestLog
  if not log then return nil, nil, readable end
  local ok2, watches = read(log.GetNumQuestWatches)
  if ok2 then readable = true end
  if ok2 and type(watches) == "number" and watches > 0 then
    local ok3, watched = read(log.GetQuestIDForQuestWatchIndex, 1)
    if ok3 and type(watched) == "number" and watched > 0 then return watched, "watched", true end
  end
  local ok4, count = read(log.GetNumQuestLogEntries)
  if ok4 then readable = true end
  if ok4 and type(count) == "number" then
    for index = 1, count do
      local ok5, info = read(log.GetInfo, index)
      if ok5 and type(info) == "table" and not open(info.isHeader) and not open(info.isHidden) then
        local first = open(info.questID)
        if type(first) == "number" and first > 0 then return first, "first", true end
      end
    end
  end
  return nil, nil, readable
end

local function questPart(missing)
  local id, pick, readable = pickQuest()
  if not id then
    if not readable then missing.quest = true end
    return NULL
  end
  local log = C_QuestLog
  local quest = { id = whole(id, 1, 10000000), pick = pick, title = NULL, complete = NULL, objectives = NULL }
  if not quest.id then
    missing.quest = true
    return NULL
  end
  local ok, title = read(log.GetTitleForQuestID, id)
  local text = ok and clean(title, TITLE_CHARS)
  if text then quest.title = text else missing["quest.title"] = true end
  local okComplete, complete = read(log.IsComplete, id)
  if okComplete and type(complete) == "boolean" then quest.complete = complete else missing["quest.complete"] = true end
  local okObjectives, found = read(log.GetQuestObjectives, id)
  local list = okObjectives and type(found) == "table" and {}
  if list then
    for index = 1, math.min(#found, MAX_OBJECTIVES) do
      local entry = found[index]
      local words = type(entry) == "table" and clean(open(entry.text), OBJECTIVE_CHARS)
      local finished = type(entry) == "table" and open(entry.finished)
      if type(words) ~= "string" or type(finished) ~= "boolean" then
        -- One objective that cannot be read makes the whole list unreadable, never a shorter list.
        list = false
        break
      end
      list[#list + 1] = {
        text = words,
        have = whole(open(entry.numFulfilled), 0, 1000000000) or NULL,
        need = whole(open(entry.numRequired), 0, 1000000000) or NULL,
        done = finished,
      }
    end
  end
  if list then quest.objectives = list else missing["quest.objectives"] = true end
  return quest
end

local function whoPart(missing)
  local who = { ref = NULL, level = NULL, class = NULL }
  local ok, level = read(UnitLevel, "player")
  local clamped = ok and whole(level, 1, 100)
  if clamped then who.level = clamped else missing["who.level"] = true end
  local okClass, _, token = read(UnitClass, "player")
  if okClass and type(token) == "string" and token:match("^[A-Z][A-Z][A-Z]+$") and #token <= 16 then
    who.class = token
  else
    missing["who.class"] = true
  end
  local okGuid, guid = read(UnitGUID, "player")
  if okGuid and type(guid) == "string" and guid ~= "" then
    who.ref = hash(salt() .. "|" .. guid)
  else
    missing["who.ref"] = true
  end
  return who
end

local function wherePart(missing)
  local where = { zone = NULL, sub = NULL, map = NULL }
  local ok, zone = read(GetRealZoneText)
  if ok then
    local text = clean(zone, TITLE_CHARS)
    if text and text ~= "" then where.zone = text end
  else
    missing["where.zone"] = true
  end
  local okSub, sub = read(GetSubZoneText)
  if okSub then
    local text = clean(sub, TITLE_CHARS)
    if text and text ~= "" then where.sub = text end
  else
    missing["where.sub"] = true
  end
  local okMap, map = read(C_Map and C_Map.GetBestMapForUnit, "player")
  if okMap then
    local id = whole(map, 0, 999999)
    if id then where.map = id end
  else
    missing["where.map"] = true
  end
  return where
end

local session = { sid = nil, seq = 0 }

-- One packet about what the game is showing now, or nil and a reason if the build cannot be read.
function ns.gather()
  if not session.sid then session.sid = hexDigits(16) end
  local okBuild, version, build, _, interface = read(GetBuildInfo)
  if not okBuild or type(version) ~= "string" or type(build) ~= "string" then return nil, "build unreadable" end
  local interfaceNumber = whole(interface, 10000, 999999)
  if not interfaceNumber then return nil, "interface unreadable" end
  local missing = {}
  local packet = {
    v = 1, kind = "context", sid = session.sid, seq = session.seq + 1, at = nil,
    build = { version = version, build = build, interface = interfaceNumber },
    scope = { quests = "one" },
  }
  local okTime, served = read(GetServerTime)
  packet.at = okTime and whole(served, 1500000000, 4100000000)
  if not packet.at then return nil, "server time unreadable" end
  packet.who = whoPart(missing)
  packet.where = wherePart(missing)
  packet.quest = questPart(missing)
  packet.missing = {}
  for _, name in ipairs(MISSING_NAMES) do
    if missing[name] then packet.missing[#packet.missing + 1] = name end
  end
  session.seq = session.seq + 1
  return packet
end

function ns.packetText()
  local packet, reason = ns.gather()
  if not packet then return nil, reason end
  local text = ns.json(packet)
  if #text > 8192 then return nil, "packet too large" end
  return text, packet
end

-- The strip: bytes, then a grid of cells. wow_helper/context/strip.py describes the layout.
local function frameBytes(text)
  local bytes = { 167, 60, 1, 0, math.floor(#text / 256), #text % 256 }
  for index = 1, #text do bytes[#bytes + 1] = text:byte(index) end
  local crc = crc16(bytes, 3, #bytes)
  bytes[#bytes + 1] = math.floor(crc / 256)
  bytes[#bytes + 1] = crc % 256
  return bytes
end
ns.frameBytes = frameBytes

function ns.cells(text, columns)
  columns = columns or COLUMNS
  local bytes = frameBytes(text)
  local bits = {}
  for _, byte in ipairs(bytes) do
    for shift = 7, 0, -1 do bits[#bits + 1] = math.floor(byte / 2 ^ shift) % 2 end
  end
  local rows = { {} }
  for index = 0, columns do rows[1][index + 1] = (index % 2 == 0) and 1 or 0 end
  local needed = math.ceil(#bits / columns)
  for number = 1, needed + needed % 2 do
    local row = {}
    for column = 1, columns do row[column] = bits[(number - 1) * columns + column] or 0 end
    row[columns + 1] = (number % 2 == 0) and 1 or 0
    rows[#rows + 1] = row
  end
  return rows
end

-- White cells merged into horizontal runs, so far fewer textures are needed than cells.
function ns.rects(grid)
  local rects = {}
  for rowIndex, row in ipairs(grid) do
    local start
    for columnIndex = 1, #row + 1 do
      local white = row[columnIndex] == 1
      if white and not start then start = columnIndex end
      if not white and start then
        rects[#rects + 1] = { row = rowIndex - 1, col = start - 1, width = columnIndex - start }
        start = nil
      end
    end
  end
  return rects
end

function ns.pixelSize()
  local okSize, _, physicalHeight = read(GetPhysicalScreenSize)
  local okHeight, height = read(UIParent.GetHeight, UIParent)
  if not (okSize and okHeight and physicalHeight and physicalHeight > 0 and height) then return nil end
  return height / physicalHeight
end

-- Drawing. Everything here is created only when a command asks for it.
local shown = { token = 0 }

local function say(...) print("WFH probe:", ...) end

local function newTexture(frame, layer)
  local texture = frame:CreateTexture(nil, layer)
  texture:SetColorTexture(layer == "BACKGROUND" and 0 or 1, layer == "BACKGROUND" and 0 or 1, layer == "BACKGROUND" and 0 or 1, 1)
  if texture.SetSnapToPixelGrid then texture:SetSnapToPixelGrid(true) end
  if texture.SetTexelSnappingBias then texture:SetTexelSnappingBias(0) end
  return texture
end

function ns.showStrip(cell, columns, seconds)
  local text, packet = ns.packetText()
  if not text then say("cannot build a packet:", packet) return end
  local pixel = ns.pixelSize()
  if not pixel then say("cannot measure the screen") return end
  local grid = ns.cells(text, columns)
  local rects = ns.rects(grid)
  local unit = cell * pixel
  local frame = shown.strip
  if not frame then
    frame = CreateFrame("Frame", "WoWCompanionProbeStrip", UIParent)
    frame:SetFrameStrata("TOOLTIP")
    frame.back = newTexture(frame, "BACKGROUND")
    frame.back:SetAllPoints(frame)
    frame.pool = {}
    frame.label = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    shown.strip = frame
  end
  local wide, tall = (columns + 1 + 2 * QUIET) * unit, (#grid + 2 * QUIET) * unit
  frame:ClearAllPoints()
  frame:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 0, 0)
  frame:SetSize(wide, tall)
  for index, rect in ipairs(rects) do
    local texture = frame.pool[index]
    if not texture then
      texture = newTexture(frame, "ARTWORK")
      frame.pool[index] = texture
    end
    texture:ClearAllPoints()
    texture:SetPoint("TOPLEFT", frame, "TOPLEFT", (QUIET + rect.col) * unit, -(QUIET + rect.row) * unit)
    texture:SetSize(rect.width * unit, unit)
    texture:Show()
  end
  for index = #rects + 1, #frame.pool do frame.pool[index]:Hide() end
  frame.label:ClearAllPoints()
  frame.label:SetPoint("TOPLEFT", frame, "BOTTOMLEFT", 0, -2)
  frame.label:SetText(string.format("WFH probe strip: %d px cells, %d columns, %d bytes, packet %d. /wfhprobe off hides it.",
    cell, columns, #text, packet.seq))
  frame:Show()
  shown.token = shown.token + 1
  local token = shown.token
  if C_Timer and C_Timer.After then
    C_Timer.After(seconds or SHOW_SECONDS, function()
      if shown.token == token and shown.strip then shown.strip:Hide() end
    end)
  end
  return text, grid, rects
end

local function copyFrame()
  if shown.copy then return shown.copy end
  local box = CreateFrame("Frame", "WoWCompanionProbeCopy", UIParent)
  box:SetFrameStrata("DIALOG")
  box:SetSize(540, 190)
  box:SetPoint("CENTER", UIParent, "CENTER", 0, 0)
  box.back = box:CreateTexture(nil, "BACKGROUND")
  box.back:SetAllPoints(box)
  box.back:SetColorTexture(0, 0, 0, 0.9)
  box.help = box:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  box.help:SetPoint("TOPLEFT", box, "TOPLEFT", 12, -10)
  box.edit = CreateFrame("EditBox", nil, box)
  box.edit:SetMultiLine(true)
  box.edit:SetAutoFocus(false)
  box.edit:SetFontObject("ChatFontNormal")
  box.edit:SetPoint("TOPLEFT", box, "TOPLEFT", 12, -34)
  box.edit:SetSize(516, 96)
  box.edit:SetScript("OnEscapePressed", function() box:Hide() end)
  box.edit:SetScript("OnTextChanged", function(self)
    if box.text and self:GetText() ~= box.text then
      self:SetText(box.text)
      self:HighlightText()
    end
  end)
  box.status = box:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  box.status:SetPoint("BOTTOMLEFT", box, "BOTTOMLEFT", 12, 12)
  shown.copy = box
  return box
end

function ns.showCopy(withButton)
  local text, packet = ns.packetText()
  if not text then say("cannot build a packet:", packet) return end
  local box = copyFrame()
  box.text = PREFIX .. text
  box.help:SetText(withButton and "Press the button, then paste somewhere to check." or "Ctrl+C to copy, then Esc.")
  box.edit:SetText(box.text)
  box.status:SetText(string.format("%d characters, packet %d.", #box.text, packet.seq))
  if withButton then
    if not box.button then
      local ok, button = pcall(CreateFrame, "Button", nil, box, "UIPanelButtonTemplate")
      if not ok then button = CreateFrame("Button", nil, box) end
      button:SetSize(200, 24)
      button:SetPoint("BOTTOMRIGHT", box, "BOTTOMRIGHT", -12, 8)
      button:SetText("Copy with the game's function")
      button:SetScript("OnClick", function()
        if type(CopyToClipboard) ~= "function" then
          box.status:SetText("CopyToClipboard is not present in this client.")
          return
        end
        local okCall, result = pcall(CopyToClipboard, box.text)
        local report = okCall and ("CopyToClipboard ran and returned " .. tostring(result))
            or ("CopyToClipboard was refused: " .. tostring(result):sub(1, 100))
        box.status:SetText(report)
        say(report)
      end)
      box.button = button
    end
    box.button:Show()
  elseif box.button then
    box.button:Hide()
  end
  box:Show()
  box.edit:SetFocus()
  box.edit:HighlightText()
  return box.text
end

function ns.hideAll()
  shown.token = shown.token + 1
  shown.liveToken = (shown.liveToken or 0) + 1
  if shown.strip then shown.strip:Hide() end
  if shown.copy then shown.copy:Hide() end
end

function ns.status()
  local _, _, build, _, interface = read(GetBuildInfo)
  build, interface = build or "?", interface or "?"
  local _, physicalWidth, physicalHeight = read(GetPhysicalScreenSize)
  local pixel = ns.pixelSize()
  say(string.format("version %s, interface %s, build %s.", VERSION, tostring(interface), tostring(build)))
  say("issecretvalue: " .. (type(issecretvalue) == "function" and "present" or "absent")
      .. "; CopyToClipboard: " .. (type(CopyToClipboard) == "function" and "present" or "absent")
      .. "; SetSnapToPixelGrid: " .. ((CreateFrame and "checked when drawing") or "n/a"))
  say(string.format("physical screen %s x %s; one pixel = %s interface units.", tostring(physicalWidth),
    tostring(physicalHeight), pixel and string.format("%.4f", pixel) or "unknown"))
end

local function usage()
  say("/wfhprobe strip [cell 2-8] [columns 32-512, even] [live]   draw the test strip at the top left")
  say("/wfhprobe copy         show the packet as text to copy with Ctrl+C")
  say("/wfhprobe copy api     show it with a button that tries the game's own clipboard function")
  say("/wfhprobe status       report which interface features this client has")
  say("/wfhprobe off          hide everything")
end

function ns.command(message)
  local words = {}
  for word in (message or ""):gmatch("[^ \9-\13]+") do words[#words + 1] = word:lower() end
  local verb = words[1]
  if verb == "strip" then
    local cell, columns, live = 4, COLUMNS, false
    for index = 2, #words do
      local number = tonumber(words[index])
      if words[index] == "live" then
        live = true
      elseif number and number >= 2 and number <= 8 and index == 2 then
        cell = math.floor(number)
      elseif number and number >= 32 and number <= 512 and number % 2 == 0 then
        columns = number
      else
        usage()
        return
      end
    end
    shown.liveToken = (shown.liveToken or 0) + 1
    ns.showStrip(cell, columns)
    if live and C_Timer and C_Timer.After then
      -- Redraw every two seconds for half a minute, each time with the next packet number, so the
      -- helper can be shown a stream of strips to tell new from repeated.
      local mine, remaining = shown.liveToken, SHOW_SECONDS * 2
      local function step()
        if shown.liveToken ~= mine or remaining <= 0 then return end
        remaining = remaining - 2
        ns.showStrip(cell, columns, 4)
        C_Timer.After(2, step)
      end
      C_Timer.After(2, step)
    end
  elseif verb == "copy" then
    ns.showCopy(words[2] == "api")
  elseif verb == "status" then
    ns.status()
  elseif verb == "off" then
    ns.hideAll()
  else
    usage()
  end
end

SLASH_WFHPROBE1 = "/wfhprobe"
if SlashCmdList then SlashCmdList["WFHPROBE"] = ns.command end
