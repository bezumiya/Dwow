-- Events.lua - transient UI/game state and the one-second export ticker.
local ADDON, ns = ...

local ev = {
	mail = false, bank = false, guildbank = false, ah = false, vendor = false,
	trainer = false, stable = false, barber = false, reading = false,
	taximap = false, trade = false, petition = false, cinematic = false,
	spiritHealer = false, duelOpponent = nil, duelAt = 0,
	resser = nil, resAt = 0, inviter = nil, inviteAt = 0, encounterName = nil,
}
ns.ACTIVITY_STATE = ev

-- C_Timer was introduced after Wrath 3.3.5. Ascension uses that client, so an
-- OnUpdate frame provides the same repeating callback without external libs.
local function NewTicker(seconds, callback)
	if C_Timer and C_Timer.NewTicker then return C_Timer.NewTicker(seconds, callback) end
	local elapsed = 0
	local tickerFrame = CreateFrame("Frame")
	tickerFrame:SetScript("OnUpdate", function(_, delta)
		elapsed = elapsed + delta
		if elapsed >= seconds then
			elapsed = elapsed - seconds
			callback()
		end
	end)
	return tickerFrame
end

local UI_EVENTS = {
	MAIL_SHOW = { "mail", true }, MAIL_CLOSED = { "mail", false },
	BANKFRAME_OPENED = { "bank", true }, BANKFRAME_CLOSED = { "bank", false },
	GUILDBANKFRAME_OPENED = { "guildbank", true }, GUILDBANKFRAME_CLOSED = { "guildbank", false },
	AUCTION_HOUSE_SHOW = { "ah", true }, AUCTION_HOUSE_CLOSED = { "ah", false },
	MERCHANT_SHOW = { "vendor", true }, MERCHANT_CLOSED = { "vendor", false },
	TRAINER_SHOW = { "trainer", true }, TRAINER_CLOSED = { "trainer", false },
	PET_STABLE_SHOW = { "stable", true }, PET_STABLE_CLOSED = { "stable", false },
	BARBER_SHOP_OPEN = { "barber", true }, BARBER_SHOP_CLOSE = { "barber", false },
	ITEM_TEXT_BEGIN = { "reading", true }, ITEM_TEXT_CLOSED = { "reading", false },
	TAXIMAP_OPENED = { "taximap", true }, TAXIMAP_CLOSED = { "taximap", false },
	TRADE_SHOW = { "trade", true }, TRADE_CLOSED = { "trade", false },
	PETITION_SHOW = { "petition", true }, PETITION_CLOSED = { "petition", false },
	CINEMATIC_START = { "cinematic", true }, CINEMATIC_STOP = { "cinematic", false },
	PLAY_MOVIE = { "cinematic", true }, STOP_MOVIE = { "cinematic", false },
	AREA_SPIRIT_HEALER_IN_RANGE = { "spiritHealer", true },
	AREA_SPIRIT_HEALER_OUT_OF_RANGE = { "spiritHealer", false },
}

function ns.InstallEventHandlers(flush)
	local frame, ticker = CreateFrame("Frame"), nil
	for _, name in ipairs({ "ADDON_LOADED", "PLAYER_ENTERING_WORLD",
		"DISPLAY_SIZE_CHANGED", "UI_SCALE_CHANGED", "PLAYER_FLAGS_CHANGED" }) do
		pcall(frame.RegisterEvent, frame, name)
	end
	for name in pairs(UI_EVENTS) do pcall(frame.RegisterEvent, frame, name) end

	local interactionKeys = {}
	if Enum and Enum.PlayerInteractionType then
		local map = { Banker = "bank", GuildBanker = "guildbank", MailInfo = "mail",
			Merchant = "vendor", Auctioneer = "ah", Barber = "barber",
			StableMaster = "stable", Trainer = "trainer", TaxiNode = "taximap" }
		for enumName, key in pairs(map) do
			local id = Enum.PlayerInteractionType[enumName]
			if id then interactionKeys[id] = key end
		end
		pcall(frame.RegisterEvent, frame, "PLAYER_INTERACTION_MANAGER_FRAME_SHOW")
		pcall(frame.RegisterEvent, frame, "PLAYER_INTERACTION_MANAGER_FRAME_HIDE")
	end
	for _, name in ipairs({ "DUEL_REQUESTED", "DUEL_FINISHED", "RESURRECT_REQUEST",
		"PARTY_INVITE_REQUEST", "PARTY_INVITE_CANCEL", "ENCOUNTER_START", "ENCOUNTER_END" }) do
		pcall(frame.RegisterEvent, frame, name)
	end

	frame:SetScript("OnEvent", function(_, event, arg1, arg2)
		local ui = UI_EVENTS[event]
		if ui then
			ev[ui[1]] = ui[2]
			if ui[1] == "vendor" and not ui[2] then ns.ResetDurabilityScan() end
			return
		end
		if event == "PLAYER_INTERACTION_MANAGER_FRAME_SHOW"
			or event == "PLAYER_INTERACTION_MANAGER_FRAME_HIDE" then
			local key = interactionKeys[arg1]
			if key then
				ev[key] = event == "PLAYER_INTERACTION_MANAGER_FRAME_SHOW"
				if key == "vendor" and not ev[key] then ns.ResetDurabilityScan() end
			end
			return
		end
		if event == "ADDON_LOADED" and arg1 == ADDON then
			DwowDB = DwowDB or { hidden = false }
		elseif event == "PLAYER_ENTERING_WORLD" then
			ev.duelOpponent, ev.resser, ev.inviter, ev.encounterName = nil, nil, nil, nil
			for _, key in ipairs({ "mail", "bank", "guildbank", "ah", "vendor", "trainer",
				"stable", "barber", "reading", "taximap", "trade", "petition",
				"cinematic", "spiritHealer" }) do ev[key] = false end
			ns.SetStripShown(not DwowDB.hidden)
			if not ticker then ticker = NewTicker(1, flush) end
		elseif event == "DISPLAY_SIZE_CHANGED" or event == "UI_SCALE_CHANGED" then
			ns.RescaleStrip()
		elseif event == "PLAYER_FLAGS_CHANGED" and (not arg1 or arg1 == "player") then
			-- AFK/DND is latency-sensitive for presence; do not wait for the ticker.
			flush()
		elseif event == "DUEL_REQUESTED" then ev.duelOpponent, ev.duelAt = arg1, GetTime()
		elseif event == "DUEL_FINISHED" then ev.duelOpponent = nil
		elseif event == "RESURRECT_REQUEST" then ev.resser, ev.resAt = arg1, GetTime()
		elseif event == "PARTY_INVITE_REQUEST" then ev.inviter, ev.inviteAt = arg1, GetTime()
		elseif event == "PARTY_INVITE_CANCEL" then ev.inviter = nil
		elseif event == "ENCOUNTER_START" then ev.encounterName = arg2
		elseif event == "ENCOUNTER_END" then ev.encounterName = nil end
	end)
end
