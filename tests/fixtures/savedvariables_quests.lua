-- Synthetic fixture: hand-written for tests, not taken from a game client or a real account.
-- Every value is fake: the zones, quest titles, and quest IDs (900000+) are invented.

WoWCompanionDB = {
	["schema"] = 1,
	["savedAt"] = 1790000000,
	["api"] = "classic",
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
			["objectives"] = {
				{
					["text"] = "Synthetic Parcel delivered",
					["finished"] = true,
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
			},
		}, -- [2]
		{
			["id"] = 900003,
			["title"] = "Clear the \"Example\" Mine",
			["level"] = 13,
			["group"] = 0,
			["header"] = "Otherfield",
			["complete"] = false,
			["failed"] = false,
			["objectives"] = {
				{
					["text"] = "Test Kobold slain",
					["finished"] = false,
					["have"] = 9,
					["need"] = 10,
				}, -- [1]
			},
		}, -- [3]
		{
			["id"] = 900004,
			["title"] = "Old Errand",
			["level"] = 5,
			["group"] = 0,
			["header"] = "Testvale",
			["complete"] = false,
			["failed"] = false,
			["objectives"] = {
				{
					["text"] = "Talk to the \124cffffd200Example Clerk\124r",
					["finished"] = false,
				}, -- [1]
			},
		}, -- [4]
		{
			["id"] = 900005,
			["title"] = "Ogre Trouble",
			["level"] = 18,
			["group"] = 3,
			["header"] = "Otherfield",
			["complete"] = false,
			["failed"] = false,
			["objectives"] = {
			},
		}, -- [5]
		{
			["id"] = 900006,
			["title"] = "Escort the Test Cart",
			["level"] = 12,
			["group"] = 0,
			["header"] = "Testvale",
			["complete"] = false,
			["failed"] = true,
			["objectives"] = {
			},
		}, -- [6]
	},
	["collapsedHeaders"] = {
	},
}
