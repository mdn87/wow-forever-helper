-- Synthetic fixture: hand-written for tests, not taken from a game client or a real account.
-- A snapshot from addon 0.4.0 on a modern-API client. Every value is fake: the client version,
-- build, zone, quest titles, and quest IDs (900000+) are invented.

WoWCompanionDB = {
	["schema"] = 1,
	["addon"] = "0.4.0",
	["savedAt"] = 1790000000,
	["api"] = "modern",
	["client"] = {
		["version"] = "1.60.1",
		["build"] = "99999",
		["interface"] = 16001,
	},
	["sources"] = {
		["objectives"] = "C_QuestLog",
		["distance"] = "C_QuestLog",
		["completed"] = "C_QuestLog",
		["available"] = "C_QuestLine",
		["itemLevel"] = "C_Item",
		["bags"] = "C_Container",
	},
	["player"] = {
		["level"] = 12,
		["class"] = "WARRIOR",
		["xp"] = 3400,
		["xpMax"] = 8800,
		["zone"] = "Testvale",
		["subzone"] = "Example Crossing",
	},
	["quests"] = {
		{
			["id"] = 900001,
			["title"] = "Synthetic Delivery",
			["level"] = 11,
			["group"] = 0,
			["header"] = "Testvale",
			["complete"] = true,
			["failed"] = false,
			["distance"] = 120,
			["objectives"] = {
				{
					["text"] = "Synthetic Parcel delivered",
					["finished"] = true,
					["have"] = 1,
					["need"] = 1,
				}, -- [1]
			},
		}, -- [1]
		{
			["id"] = 900002,
			["title"] = "Gather Synthetic Pelts",
			["level"] = 12,
			["group"] = 0,
			["header"] = "Testvale",
			["complete"] = false,
			["failed"] = false,
			["objectives"] = {
				{
					["text"] = "Synthetic Pelt: 3/8",
					["finished"] = false,
					["have"] = 3,
					["need"] = 8,
				}, -- [1]
				{
					["text"] = "Speak to the Example Trapper",
					["finished"] = false,
				}, -- [2]
			},
		}, -- [2]
	},
	["collapsedHeaders"] = {
		"Otherfield", -- [1]
	},
	["mapID"] = 9001,
	["completedQuests"] = {
		900010, -- [1]
		900011, -- [2]
	},
	["available"] = {
	},
	["character"] = {
		["money"] = 123456,
		["rested"] = 4400,
		["gear"] = {
			{
				["slot"] = 1,
				["id"] = 900101,
				["ilvl"] = 14,
				["durability"] = 30,
				["durabilityMax"] = 40,
			}, -- [1]
		},
		["bags"] = {
			["free"] = 12,
			["total"] = 40,
		},
	},
}
