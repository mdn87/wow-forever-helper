-- WoW Companion: copies the quest log, completed and available quests, and character status into
-- SavedVariables for wow_helper to read.
-- Read-only. It never casts, targets, moves, chats, accepts, abandons, or changes a setting,
-- and it prints nothing. The game writes WoWCompanionDB to disk on /reload and on logout.

WoWCompanionDB = WoWCompanionDB or {}

local SCHEMA = 1
local ADDON_VERSION = "0.4.0" -- keep equal to the .toc Version line

local function objectives(index, questID)
  local list = {}
  local found = questID and C_QuestLog and C_QuestLog.GetQuestObjectives
      and C_QuestLog.GetQuestObjectives(questID)
  if found then
    for _, o in ipairs(found) do
      list[#list + 1] = { text = o.text, finished = o.finished and true or false,
                          have = o.numFulfilled, need = o.numRequired }
    end
  elseif GetNumQuestLeaderBoards then
    for j = 1, GetNumQuestLeaderBoards(index) or 0 do
      local text, _, finished = GetQuestLogLeaderBoard(j, index)
      list[#list + 1] = { text = text, finished = finished and true or false }
    end
  end
  return list
end

local function distance(questID)
  -- Modern clients only; yards from the player to the nearest objective area.
  if not (questID and C_QuestLog and C_QuestLog.GetDistanceSqToQuest) then return nil end
  local squared, onContinent = C_QuestLog.GetDistanceSqToQuest(questID)
  if squared and onContinent then return math.floor(math.sqrt(squared) + 0.5) end
  return nil
end

local function entry(index, modern)
  if modern then
    local info = C_QuestLog.GetInfo(index)
    if not info or info.isHidden then return nil end
    local complete = not info.isHeader and C_QuestLog.IsComplete and C_QuestLog.IsComplete(info.questID)
    local failed = not info.isHeader and C_QuestLog.IsFailed and C_QuestLog.IsFailed(info.questID)
    return info.title, info.level, info.suggestedGroup, info.isHeader, info.isCollapsed,
           complete, failed, info.questID
  end
  local title, level, group, isHeader, isCollapsed, state, _, questID = GetQuestLogTitle(index)
  return title, level, group, isHeader, isCollapsed, state == 1, state == -1, questID
end

local function itemLevel(link)
  local detailed = (C_Item and C_Item.GetDetailedItemLevelInfo) or GetDetailedItemLevelInfo
  return link and detailed and detailed(link) or nil
end

local function gear()
  -- Equipped items by slot number (1 head ... 19 tabard): IDs and numbers only, no names.
  local list = {}
  for slot = 1, 19 do
    local id = GetInventoryItemID("player", slot)
    if id then
      local current, maximum = GetInventoryItemDurability(slot)
      list[#list + 1] = { slot = slot, id = id, ilvl = itemLevel(GetInventoryItemLink("player", slot)),
                          durability = current, durabilityMax = maximum }
    end
  end
  return list
end

local function bags()
  local numSlots = C_Container and C_Container.GetContainerNumSlots or GetContainerNumSlots
  local numFree = C_Container and C_Container.GetContainerNumFreeSlots or GetContainerNumFreeSlots
  if not (numSlots and numFree) then return nil end
  local free, total = 0, 0
  for bag = 0, 4 do -- the backpack and the four bag slots
    total = total + (numSlots(bag) or 0)
    free = free + (numFree(bag) or 0)
  end
  return { free = free, total = total }
end

local function completedQuests()
  -- Quest IDs this character has turned in. Forever and retail have the modern call;
  -- older classic clients return a table keyed by quest ID instead.
  if C_QuestLog and C_QuestLog.GetAllCompletedQuestIDs then
    return C_QuestLog.GetAllCompletedQuestIDs()
  end
  if GetQuestsCompleted then
    local ids = {}
    for id in pairs(GetQuestsCompleted() or {}) do ids[#ids + 1] = id end
    table.sort(ids)
    return ids
  end
  return nil
end

local requestedMap = nil

local function available()
  -- Quests the game says can be picked up on the current map, with map coordinates (0 to 1).
  -- Listed for Forever and retail; what Forever fills in is untested. The first read of a map
  -- asks the game to load its quest lines; QUESTLINE_UPDATE then triggers a fresh copy.
  if not (C_QuestLine and C_QuestLine.GetAvailableQuestLines and C_Map and C_Map.GetBestMapForUnit) then
    return nil, nil
  end
  local mapID = C_Map.GetBestMapForUnit("player")
  if not mapID then return nil, nil end
  if mapID ~= requestedMap and C_QuestLine.RequestQuestLinesForMap then
    requestedMap = mapID
    C_QuestLine.RequestQuestLinesForMap(mapID)
  end
  local list = {}
  for _, line in ipairs(C_QuestLine.GetAvailableQuestLines(mapID) or {}) do
    if line.questID and not line.isHidden then
      list[#list + 1] = { id = line.questID, title = line.questName, line = line.questLineName,
                          x = line.x, y = line.y, daily = line.isDailyQuest and true or false,
                          campaign = line.isCampaign and true or false }
    end
  end
  return list, mapID
end

local function character()
  return { money = GetMoney(), rested = GetXPExhaustion and GetXPExhaustion() or nil,
           gear = gear(), bags = bags() }
end

local function client()
  -- The running client's version, build, and interface number, so the helper can tell whether
  -- the .toc Interface guess matched. GetBuildInfo returns version, build, date, interface.
  if not GetBuildInfo then return nil end
  local version, build, _, interface = GetBuildInfo()
  return { version = version, build = build, interface = interface }
end

local function sources()
  -- Which API each feature read on this client, so the first real snapshot shows what exists.
  local function pick(modernName, classicName, modern, classic)
    if modern then return modernName elseif classic then return classicName end
    return "none"
  end
  return {
    objectives = pick("C_QuestLog", "leaderboard", C_QuestLog and C_QuestLog.GetQuestObjectives, GetNumQuestLeaderBoards),
    distance = (C_QuestLog and C_QuestLog.GetDistanceSqToQuest) and "C_QuestLog" or "none",
    completed = pick("C_QuestLog", "GetQuestsCompleted", C_QuestLog and C_QuestLog.GetAllCompletedQuestIDs, GetQuestsCompleted),
    available = (C_QuestLine and C_QuestLine.GetAvailableQuestLines and C_Map and C_Map.GetBestMapForUnit)
                and "C_QuestLine" or "none",
    itemLevel = pick("C_Item", "global", C_Item and C_Item.GetDetailedItemLevelInfo, GetDetailedItemLevelInfo),
    bags = pick("C_Container", "global", C_Container and C_Container.GetContainerNumSlots, GetContainerNumSlots),
  }
end

local function snapshot()
  local modern = C_QuestLog and C_QuestLog.GetInfo and true or false
  local count = modern and C_QuestLog.GetNumQuestLogEntries() or GetNumQuestLogEntries()
  local quests, collapsed, header = {}, {}, nil
  for index = 1, count or 0 do
    local title, level, group, isHeader, isCollapsed, complete, failed, questID = entry(index, modern)
    if title and isHeader then
      header = title
      if isCollapsed then collapsed[#collapsed + 1] = title end
    elseif title then
      quests[#quests + 1] = {
        id = questID, title = title, level = level, group = group, header = header,
        complete = complete and true or false, failed = failed and true or false,
        distance = distance(questID), objectives = objectives(index, questID),
      }
    end
  end
  local _, class = UnitClass("player")
  local nearby, mapID = available()
  return {
    schema = SCHEMA, addon = ADDON_VERSION, savedAt = GetServerTime(), api = modern and "modern" or "classic",
    client = client(), sources = sources(),
    player = { level = UnitLevel("player"), class = class, xp = UnitXP("player"),
               xpMax = UnitXPMax("player"), zone = GetRealZoneText(), subzone = GetSubZoneText() },
    quests = quests, collapsedHeaders = collapsed, character = character(),
    completedQuests = completedQuests(), available = nearby, mapID = mapID,
  }
end

local pending = false
local frame = CreateFrame("Frame")
for _, event in ipairs({ "PLAYER_ENTERING_WORLD", "QUEST_LOG_UPDATE", "ZONE_CHANGED_NEW_AREA", "PLAYER_LOGOUT",
                         "PLAYER_MONEY", "PLAYER_EQUIPMENT_CHANGED", "UPDATE_INVENTORY_DURABILITY",
                         "BAG_UPDATE_DELAYED", "QUEST_TURNED_IN", "QUESTLINE_UPDATE" }) do
  -- Registering an event a client does not know raises an error; skip it instead.
  pcall(frame.RegisterEvent, frame, event)
end
frame:SetScript("OnEvent", function(_, event)
  if event == "PLAYER_LOGOUT" then
    -- The quest API can come back empty during teardown; keep the last good copy then.
    local last = snapshot()
    if #last.quests > 0 or not WoWCompanionDB.quests then WoWCompanionDB = last end
  elseif not pending then
    -- QUEST_LOG_UPDATE fires in bursts; take one copy after the burst settles.
    pending = true
    C_Timer.After(2, function()
      pending = false
      WoWCompanionDB = snapshot()
    end)
  end
end)
