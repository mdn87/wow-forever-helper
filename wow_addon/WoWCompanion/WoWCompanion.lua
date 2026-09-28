-- WoW Companion: copies the quest log into SavedVariables for wow_helper to read.
-- Read-only. It never casts, targets, moves, chats, accepts, abandons, or changes a setting,
-- and it prints nothing. The game writes WoWCompanionDB to disk on /reload and on logout.

WoWCompanionDB = WoWCompanionDB or {}

local SCHEMA = 1

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
  return {
    schema = SCHEMA, savedAt = GetServerTime(), api = modern and "modern" or "classic",
    player = { level = UnitLevel("player"), class = class, xp = UnitXP("player"),
               xpMax = UnitXPMax("player"), zone = GetRealZoneText(), subzone = GetSubZoneText() },
    quests = quests, collapsedHeaders = collapsed,
  }
end

local pending = false
local frame = CreateFrame("Frame")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:RegisterEvent("QUEST_LOG_UPDATE")
frame:RegisterEvent("ZONE_CHANGED_NEW_AREA")
frame:RegisterEvent("PLAYER_LOGOUT")
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
