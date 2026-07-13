-- Core.lua — collects character data (official API only, read-only) and
-- triggers a draw once per second. Fields and order: docs/PROTOCOLO.md.
-- The "activity" field carries the current special activity as a compact token
-- ("hearth:Orgrimmar", "ah", "flag", "breath:37"...) — tokens in PROTOCOLO.md.

local ADDON, ns = ...

local ticker
local wasFalling = false  -- IsFalling is true during jumps; only report after 2 consecutive ticks
local idleTicks = 0
local durTick, durLowPct = 0, nil
local ticksSinceSwim = 9999  -- waterwalk is only newsworthy near water

-- The global GetSpellInfo was removed in the MoP Classic client (11.x base);
-- there the name comes from C_Spell.GetSpellInfo(id).name
local GetSpellName = GetSpellInfo
	or (C_Spell and C_Spell.GetSpellInfo and function(id)
		local info = C_Spell.GetSpellInfo(id)
		return info and info.name
	end)
	or function() return nil end

-- localized spell names used in comparisons (locale-proof)
local FISHING = GetSpellName(7620) or "Fishing"
local S_SMELT = GetSpellName(2656)
local S_DISENCH = GetSpellName(13262)
local S_MINE = GetSpellName(2575)
local S_HERB = GetSpellName(2366)
local S_SKIN = GetSpellName(8613)
local S_FIRSTAID = GetSpellName(746)
local S_PROSPECT = GetSpellName(31252)
local S_MILL = GetSpellName(51005)
local S_FOOD = GetSpellName(433)
local S_DRINK = GetSpellName(430)

-- mage teleports/portals → city (stable spellIDs; audited table)
local TELEPORT_CITY = {
	[3561] = "Stormwind", [3562] = "Ironforge", [3565] = "Darnassus",
	[3563] = "Undercity", [3566] = "Thunder Bluff", [3567] = "Orgrimmar",
	[32271] = "Exodar", [32272] = "Silvermoon", [33690] = "Shattrath",
	[35715] = "Shattrath", [53140] = "Dalaran", [49358] = "Theramore",
	[49359] = "Stonard", [88342] = "Tol Barad", [88344] = "Tol Barad",
	[132621] = "Vale das Flores Eternas", [132627] = "Vale das Flores Eternas",
}
local PORTAL_CITY = {
	[10059] = "Stormwind", [11416] = "Ironforge", [11419] = "Darnassus",
	[11418] = "Undercity", [11420] = "Thunder Bluff", [11417] = "Orgrimmar",
	[32266] = "Exodar", [32267] = "Silvermoon", [33691] = "Shattrath",
	[35717] = "Shattrath", [53142] = "Dalaran", [49360] = "Theramore",
	[49361] = "Stonard", [88345] = "Tol Barad", [88346] = "Tol Barad",
	[132620] = "Vale das Flores Eternas", [132626] = "Vale das Flores Eternas",
}

-- event-driven state (UI windows and one-off happenings)
local ev = {
	mail = false, bank = false, guildbank = false, ah = false, vendor = false,
	trainer = false, stable = false, barber = false, reading = false,
	taximap = false, trade = false, petition = false, cinematic = false,
	spiritHealer = false,
	duelOpponent = nil, duelAt = 0,
	resser = nil, resAt = 0,
	inviter = nil, inviteAt = 0,
	encounterName = nil,
}

local function Sanitize(v, maxBytes)
	v = tostring(v or "")
	-- "|" is the protocol's field separator (and WoW's escape character)
	v = v:gsub("|", "/")
	-- per-field cap: without it, long names add up past the Encoder's 600-byte
	-- limit, which would cut by byte in the MIDDLE of a field (silent corruption)
	if maxBytes and #v > maxBytes then
		local cut = maxBytes
		-- don't cut in the middle of a UTF-8 character (continuation bytes 0x80-0xBF)
		while cut > 0 do
			local nxt = v:byte(cut + 1)
			if not nxt or nxt < 128 or nxt >= 192 then break end
			cut = cut - 1
		end
		v = v:sub(1, cut)
	end
	return v
end

-- byte limits per free-text field (indices of the list in BuildPayload)
local FIELD_LIMITS = {
	[1] = 36, [2] = 40, [4] = 30, [5] = 30, [7] = 60, [8] = 60, [9] = 60,
	[16] = 48, [20] = 48, [25] = 40, [27] = 80, [31] = 48,
}

-- UnitBuff is also gone in MoP Classic; there it's C_UnitAuras
local function BuffAt(i)
	if UnitBuff then
		local name, _, _, _, _, _, _, _, _, sid = UnitBuff("player", i)
		return name, sid
	end
	if C_UnitAuras and C_UnitAuras.GetBuffDataByIndex then
		local aura = C_UnitAuras.GetBuffDataByIndex("player", i)
		if aura then return aura.name, aura.spellId end
	end
	return nil
end

-- single buff scan per tick
local function ScanBuffs()
	local b = { slowfall = false, waterwalk = false, feign = false,
		eating = false, drinking = false, flag = false }
	for i = 1, 40 do
		local name, sid = BuffAt(i)
		if not name then break end
		if sid == 130 or sid == 1706 then b.slowfall = true end
		if sid == 546 or sid == 3714 or sid == 11319 then b.waterwalk = true end
		if sid == 5384 then b.feign = true end
		if sid == 23333 or sid == 23335 or sid == 34976 then b.flag = true end
		-- Temple of Kotmogu orbs (MoP) count as "carrying an objective"
		if sid == 121164 or sid == 121175 or sid == 121176 or sid == 121177 then
			b.flag = true
		end
		if name == S_FOOD then b.eating = true end
		if name == S_DRINK then b.drinking = true end
	end
	return b
end

-- breath/fatigue: current pct only via GetMirrorTimerProgress (the 2nd return
-- of GetMirrorTimerInfo is the timer's INITIAL value, not the current one);
-- scale < 0 means draining — recovering at the surface is not newsworthy
local function MirrorToken()
	if not GetMirrorTimerInfo then return nil end
	for i = 1, 3 do
		local timer, _, maxv, scale = GetMirrorTimerInfo(i)
		if (timer == "BREATH" or timer == "EXHAUSTION")
			and maxv and maxv > 0 and scale and scale < 0 then
			local cur = GetMirrorTimerProgress and GetMirrorTimerProgress(timer) or maxv
			local pct = math.max(0, math.min(100, math.floor(cur / maxv * 100 + 0.5)))
			return (timer == "BREATH" and "breath:" or "fatigue:") .. pct
		end
	end
	return nil
end

-- dungeon/raid queue: GetLFGMode only exists in MoP; C_LFGList (LFG Tool /
-- premade groups) exists in Era, Anniversary and MoP — all guarded.
-- The LE_LFG_CATEGORY_* constants may be nil in Classic clients, so the
-- canonical numeric values serve as fallbacks (1=LFD, 2=LFR, 3=RF)
local function LfgActivity()
	if GetLFGMode then
		local cats = {
			{ LE_LFG_CATEGORY_LFD or 1, "lfd" },
			{ LE_LFG_CATEGORY_RF or 3, "rf" },
			{ LE_LFG_CATEGORY_LFR or 2, "rf" },
		}
		for _, c in ipairs(cats) do
			local ok, mode = pcall(GetLFGMode, c[1])
			if ok and mode then
				if mode == "proposal" or mode == "rolecheck" then return "lfgpop" end
				if mode == "queued" or mode == "suspended" then return c[2] end
			end
		end
		-- old signature (no category): GetLFGMode() returns the mode directly
		local ok, mode = pcall(GetLFGMode)
		if ok and mode then
			if mode == "proposal" or mode == "rolecheck" then return "lfgpop" end
			if mode == "queued" or mode == "suspended" then return "lfd" end
		end
	end
	if C_LFGList then
		if C_LFGList.GetApplications and C_LFGList.GetApplicationInfo then
			for _, resultID in ipairs(C_LFGList.GetApplications() or {}) do
				local _, appStatus = C_LFGList.GetApplicationInfo(resultID)
				if appStatus == "applied" or appStatus == "invited" then return "lfgapp" end
			end
		end
		if C_LFGList.HasActiveEntryInfo and C_LFGList.HasActiveEntryInfo() then
			return "lfglist"
		end
	end
	return nil
end

-- durTick advances in BuildPayload (every tick), not here: otherwise the 10s
-- sampling would only count ticks where the priority chain reaches lowdur
local function DurabilityLow()
	if durTick % 10 == 1 and GetInventoryItemDurability then
		local cur, max, broken = 0, 0, false
		for slot = 1, 18 do  -- 18 = ranged (exists in Era; nil in MoP, harmless)
			local c, m = GetInventoryItemDurability(slot)
			if c and m and m > 0 then
				cur = cur + c
				max = max + m
				if c == 0 then broken = true end
			end
		end
		if max > 0 then
			local pct = math.floor(cur / max * 100 + 0.5)
			durLowPct = (pct < 25 or broken) and pct or nil
		else
			durLowPct = nil
		end
	end
	return durLowPct
end

-- active mount via C_MountJournal (exists in Era 1.15+, Anniversary and MoP).
-- The scan walks the entire collection, so it only runs when needed:
-- on mounting (unknown spell) and every ~5s while mounted (mount swap)
local mountName, mountSpell, mountTick = "", 0, 0
local function ScanMount(mounted)
	if not mounted then
		mountName, mountSpell, mountTick = "", 0, 0
		return
	end
	mountTick = mountTick + 1
	-- ALWAYS gate by tick: without this, a mount missing from the journal
	-- (Era item) would make the full collection scan run every second
	if mountTick ~= 1 and mountTick % 5 ~= 1 then return end
	if not (C_MountJournal and C_MountJournal.GetMountIDs
		and C_MountJournal.GetMountInfoByID) then return end
	local ok, ids = pcall(C_MountJournal.GetMountIDs)
	if not ok or type(ids) ~= "table" then return end
	for i = 1, #ids do
		local ok2, name, spellID, _, active = pcall(C_MountJournal.GetMountInfoByID, ids[i])
		if ok2 and active then
			mountName, mountSpell = name or "", spellID or 0
			return
		end
	end
	-- rescan with no active mount: don't keep the previous name (stale)
	mountName, mountSpell = "", 0
end

local function BattlefieldQueue()
	if not GetMaxBattlefieldID or not GetBattlefieldStatus then return nil, nil end
	local queued, confirm
	for i = 1, GetMaxBattlefieldID() do
		local status, mapName = GetBattlefieldStatus(i)
		if status == "confirm" then
			confirm = mapName or "?"
		elseif status == "queued" then
			queued = mapName or "?"
		end
	end
	return queued, confirm
end

-- decides the current special activity; check order equals priority
local function BuildActivity(instType, instanceID, buffs, falling, ghost)
	if buffs.flag then return "flag" end
	if ev.encounterName then return "boss:" .. ev.encounterName end

	local mirror = MirrorToken()
	if mirror then return mirror end

	-- queue pops are urgent (they expire in seconds); being IN the queue is
	-- background status — that's why confirm goes up here and queued stays below
	local queued, confirm = BattlefieldQueue()
	if confirm then return "bgconfirm:" .. confirm end
	local lfg = LfgActivity()
	if lfg == "lfgpop" then return lfg end

	-- do NOT use "X and f()" here: in Lua the expression truncates multiple
	-- returns to a single one and castId would be nil forever
	local castName, castId
	if UnitCastingInfo then
		castName, _, _, _, _, _, _, _, castId = UnitCastingInfo("player")
	end
	if castId == 8690 or castId == 556 then
		return "hearth:" .. ((GetBindLocation and GetBindLocation()) or "")
	end
	if castId and TELEPORT_CITY[castId] then return "teleport:" .. TELEPORT_CITY[castId] end
	if castId and PORTAL_CITY[castId] then return "portal:" .. PORTAL_CITY[castId] end
	if castName then
		if castName == S_SMELT then return "smelt" end
		if castName == S_DISENCH then return "disenchant" end
		if castName == S_MINE then return "mine" end
		if castName == S_HERB then return "herb" end
		if castName == S_SKIN then return "skin" end
		if castName == S_PROSPECT then return "prospect" end
		if castName == S_MILL then return "mill" end
	end
	local chanName = UnitChannelInfo and UnitChannelInfo("player")
	if chanName and chanName == S_FIRSTAID then return "firstaid" end

	if ev.resser then return "res:" .. ev.resser end
	if ev.spiritHealer and ghost and GetAreaSpiritHealerTime then
		return "spirit:" .. math.floor(GetAreaSpiritHealerTime() or 0)
	end
	if ev.duelOpponent then return "duel:" .. ev.duelOpponent end
	if ev.trade then return "trade:" .. (UnitName("NPC") or "?") end
	if ev.cinematic then return "cinematic" end
	if UnitInVehicle and UnitInVehicle("player") then
		return "vehicle:" .. (UnitName("vehicle") or "")
	end

	if instType == "pvp" and GetBattlefieldWinner then
		local w = GetBattlefieldWinner()
		if w then
			local faction = UnitFactionGroup("player")
			if w == 255 then return "bgtie" end
			if (w == 0 and faction == "Horde") or (w == 1 and faction == "Alliance") then
				return "bgwin"
			end
			return "bgloss"
		end
	end

	if ev.ah then return "ah" end
	if ev.mail then return "mail" end
	if ev.guildbank then return "guildbank" end
	if ev.bank then return "bank" end
	if ev.vendor then
		if CanMerchantRepair and CanMerchantRepair() and GetRepairAllCost and GetRepairAllCost() > 0 then
			return "repair"
		end
		return "vendor"
	end
	if ev.trainer then return "trainer" end
	if ev.stable then return "stable" end
	if ev.barber then return "barber" end
	if ev.reading then return "read" end
	if ev.taximap then return "taximap" end
	if ev.petition then return "petition" end
	if ev.inviter then return "invite:" .. ev.inviter end

	if buffs.feign then return "feign" end
	if buffs.eating and buffs.drinking then return "eatdrink" end
	if buffs.eating then return "eat" end
	if buffs.drinking then return "drink" end
	if falling and buffs.slowfall then return "floatfall" end
	-- only newsworthy up to ~2 min after leaving the water; otherwise the
	-- 10-min buff becomes the headline in the middle of Orgrimmar
	if buffs.waterwalk and IsSwimming and not IsSwimming()
		and ticksSinceSwim < 120 then
		return "waterwalk"
	end
	if instanceID == 369 then return "tram" end
	if UnitIsPVPFreeForAll and UnitIsPVPFreeForAll("player") then return "ffa" end
	if GetRaidTargetIndex and GetRaidTargetIndex("player") == 8 then return "skull" end

	local low = DurabilityLow()
	if low then return "lowdur:" .. low end

	if queued then return "bgqueue:" .. queued end
	if lfg then return lfg end

	-- idle: standing still, not casting, out of combat, for 5+ minutes
	-- (idleTicks is counted in BuildPayload, which runs EVERY tick; not here,
	-- otherwise an open window would freeze the counter instead of resetting it)
	if idleTicks >= 300 then return "idle:" .. math.floor(idleTicks / 60) end

	return ""
end

-- runs every tick, BEFORE activity prioritization
local function TickCounters()
	durTick = durTick + 1
	if IsPlayerMoving and not IsPlayerMoving() and not UnitAffectingCombat("player")
		and not (UnitCastingInfo and UnitCastingInfo("player"))
		and not (UnitChannelInfo and UnitChannelInfo("player"))
		and not UnitOnTaxi("player") then
		idleTicks = idleTicks + 1
	else
		idleTicks = 0
	end
end

local function BuildPayload()
	TickCounters()
	local classLoc, classToken = UnitClass("player")
	local raceLoc, raceToken = UnitRace("player")
	local hp, hpMax = UnitHealth("player"), UnitHealthMax("player")
	local xp, xpMax = UnitXP("player"), UnitXPMax("player")
	local instName, instType, difficultyID, _, instMaxPlayers, _, _, instanceID = GetInstanceInfo()
	local inInstance = instType ~= nil and instType ~= "none"
	local ghost = UnitIsGhost("player")

	-- state bitfield: 1 taxi, 2 combat, 4 resting, 8 mounted,
	-- 16 swimming, 32 AFK, 64 ghost, 128 stealthed, 256 flying, 512 falling,
	-- 1024 fishing (mirrored in decoder.py)
	local flags = 0
	if UnitOnTaxi("player") then flags = flags + 1 end
	if UnitAffectingCombat("player") then flags = flags + 2 end
	if IsResting() then flags = flags + 4 end
	-- IsMounted() is also true during taxi flight; bit 8 must mean mount only
	local mounted = IsMounted() and not UnitOnTaxi("player")
	if mounted then flags = flags + 8 end
	ScanMount(mounted)
	if IsSwimming() then
		flags = flags + 16
		ticksSinceSwim = 0
	else
		ticksSinceSwim = ticksSinceSwim + 1
	end
	if UnitIsAFK("player") then flags = flags + 32 end
	if ghost then flags = flags + 64 end
	if IsStealthed() then flags = flags + 128 end
	if IsFlying and IsFlying() then flags = flags + 256 end
	local fallingNow = (IsFalling and IsFalling()) or false
	local falling = fallingNow and wasFalling and not UnitOnTaxi("player")
	if falling then flags = flags + 512 end
	wasFalling = fallingNow
	if UnitChannelInfo and UnitChannelInfo("player") == FISHING then flags = flags + 1024 end

	-- active shapeshift form (druid/shaman): localized name + spellID.
	-- The GetShapeshiftFormInfo signature differs between clients: the classic
	-- one returns (icon, name, active), the modern one (icon, active, castable, spellID)
	local formName, formId = "", 0
	if GetShapeshiftForm and GetShapeshiftFormInfo then
		local idx = GetShapeshiftForm()
		if idx and idx > 0 then
			local r1, r2, r3, r4 = GetShapeshiftFormInfo(idx)
			if type(r2) == "string" then
				formName = r2
			elseif type(r4) == "number" then
				formId = r4
				formName = GetSpellName(r4) or ""
			end
		end
	end

	local targetName, targetHp, targetClass, targetLevel = "", 0, "", 0
	if UnitExists("target") and UnitCanAttack("player", "target")
		and not UnitIsDeadOrGhost("target") then
		targetName = UnitName("target") or ""
		local thp, thpMax = UnitHealth("target"), UnitHealthMax("target")
		targetHp = thpMax > 0 and math.floor(thp / thpMax * 100 + 0.5) or 0
		targetClass = UnitClassification("target") or "normal"
		-- -1 = level "??" (boss far above); the companion handles it
		targetLevel = UnitLevel("target") or 0
	end

	-- cleanup of one-off states that expire on their own
	local now = GetTime()
	if ev.resser and (not UnitIsDeadOrGhost("player") or now - ev.resAt > 60) then
		ev.resser = nil
	end
	if ev.inviter and (GetNumGroupMembers() > 0 or now - ev.inviteAt > 60) then
		ev.inviter = nil
	end
	if ev.duelOpponent and now - ev.duelAt > 600 then
		ev.duelOpponent = nil
	end

	local buffs = ScanBuffs()
	local activity = BuildActivity(instType, instanceID, buffs, falling, ghost)

	local fields = {
		UnitName("player"),
		GetRealmName(),
		classToken,
		classLoc,
		raceLoc,
		UnitLevel("player"),
		GetRealZoneText(),
		GetSubZoneText(),
		inInstance and instName or "",
		instType or "none",
		hpMax > 0 and math.floor(hp / hpMax * 100 + 0.5) or 0,
		UnitIsDeadOrGhost("player") and 1 or 0,
		xpMax > 0 and math.floor(xp / xpMax * 100 + 0.5) or 0,
		GetNumGroupMembers(),
		(inInstance and instMaxPlayers and instMaxPlayers > 0) and instMaxPlayers
			or (IsInRaid() and 40 or 5),
		GetGuildInfo("player") or "",
		-- fields 17+ are v1 protocol appendices: the decoder tolerates absence
		raceToken or "",
		UnitSex("player") == 3 and "f" or "m",
		flags,
		targetName,
		targetHp,
		targetClass,
		GetMoney(),
		UnitFactionGroup("player") or "",
		formName,
		formId,
		activity,
		-- fields 28-31 (appendices): difficulty, target level, active mount
		inInstance and (difficultyID or 0) or 0,
		targetLevel,
		mountSpell,
		mountName,
	}
	for i = 1, #fields do
		fields[i] = Sanitize(fields[i], FIELD_LIMITS[i])
	end
	return table.concat(fields, "|")
end

local function Flush()
	if DiscordWowDB.hidden then return end
	ns.Draw(BuildPayload())
end

local f = CreateFrame("Frame")
f:RegisterEvent("ADDON_LOADED")
f:RegisterEvent("PLAYER_ENTERING_WORLD")
f:RegisterEvent("DISPLAY_SIZE_CHANGED")
f:RegisterEvent("UI_SCALE_CHANGED")

-- open/close pairs of UI windows → key in ev
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
for eventName in pairs(UI_EVENTS) do
	-- pcall: some events don't exist in every flavor (e.g. guild bank and
	-- barber shop don't exist in Era)
	pcall(f.RegisterEvent, f, eventName)
end

-- 10.x+ base clients (MoP Classic) migrated several panels to the
-- PlayerInteractionManager; the legacy events above may not even fire there
local INTERACTION_KEYS = {}
if Enum and Enum.PlayerInteractionType then
	local map = {
		Banker = "bank", GuildBanker = "guildbank", MailInfo = "mail",
		Merchant = "vendor", Auctioneer = "ah", Barber = "barber",
		StableMaster = "stable", Trainer = "trainer", TaxiNode = "taximap",
	}
	for enumName, evKey in pairs(map) do
		local id = Enum.PlayerInteractionType[enumName]
		if id then INTERACTION_KEYS[id] = evKey end
	end
	pcall(f.RegisterEvent, f, "PLAYER_INTERACTION_MANAGER_FRAME_SHOW")
	pcall(f.RegisterEvent, f, "PLAYER_INTERACTION_MANAGER_FRAME_HIDE")
end
for _, eventName in ipairs({
	"DUEL_REQUESTED", "DUEL_FINISHED", "RESURRECT_REQUEST",
	"PARTY_INVITE_REQUEST", "PARTY_INVITE_CANCEL",
	"ENCOUNTER_START", "ENCOUNTER_END",
}) do
	pcall(f.RegisterEvent, f, eventName)
end

f:SetScript("OnEvent", function(_, event, arg1, arg2)
	local ui = UI_EVENTS[event]
	if ui then
		ev[ui[1]] = ui[2]
		if ui[1] == "vendor" and not ui[2] then
			durTick = 0  -- left the vendor: durability rescan on the next tick
		end
		return
	end
	if event == "PLAYER_INTERACTION_MANAGER_FRAME_SHOW"
		or event == "PLAYER_INTERACTION_MANAGER_FRAME_HIDE" then
		local key = INTERACTION_KEYS[arg1]
		if key then
			ev[key] = event == "PLAYER_INTERACTION_MANAGER_FRAME_SHOW"
			if key == "vendor" and not ev[key] then durTick = 0 end
		end
		return
	end
	if event == "ADDON_LOADED" and arg1 == ADDON then
		DiscordWowDB = DiscordWowDB or { hidden = false }
	elseif event == "PLAYER_ENTERING_WORLD" then
		-- one-off states don't survive a loading screen
		ev.duelOpponent, ev.resser, ev.inviter = nil, nil, nil
		ev.encounterName = nil
		-- UI windows: the *_CLOSED event is lost on a portal/summon with the
		-- window open and the flag would stay stuck ("at the auction house" forever)
		for _, key in ipairs({ "mail", "bank", "guildbank", "ah", "vendor",
			"trainer", "stable", "barber", "reading", "taximap", "trade",
			"petition", "cinematic", "spiritHealer" }) do
			ev[key] = false
		end
		ns.SetStripShown(not DiscordWowDB.hidden)
		if not ticker then
			ticker = C_Timer.NewTicker(1, Flush)
		end
	elseif event == "DISPLAY_SIZE_CHANGED" or event == "UI_SCALE_CHANGED" then
		ns.RescaleStrip()
	elseif event == "DUEL_REQUESTED" then
		ev.duelOpponent, ev.duelAt = arg1, GetTime()
	elseif event == "DUEL_FINISHED" then
		ev.duelOpponent = nil
	elseif event == "RESURRECT_REQUEST" then
		ev.resser, ev.resAt = arg1, GetTime()
	elseif event == "PARTY_INVITE_REQUEST" then
		ev.inviter, ev.inviteAt = arg1, GetTime()
	elseif event == "PARTY_INVITE_CANCEL" then
		ev.inviter = nil
	elseif event == "ENCOUNTER_START" then
		ev.encounterName = arg2
	elseif event == "ENCOUNTER_END" then
		ev.encounterName = nil
	end
end)

local function Print(msg)
	print("|cff5865f2DiscordWow|r: " .. msg)
end

SLASH_DISCORDWOW1 = "/dwow"
SlashCmdList.DISCORDWOW = function(msg)
	local cmd = (msg or ""):lower():match("^%s*(%S*)")
	if cmd == "" or cmd == "toggle" then
		DiscordWowDB.hidden = not DiscordWowDB.hidden
		ns.SetStripShown(not DiscordWowDB.hidden)
		Print(DiscordWowDB.hidden
			and "export desativado (o companion vai limpar o presence)"
			or "export ativado")
	elseif cmd == "status" then
		Print((DiscordWowDB.hidden and "oculto" or "ativo") .. " — payload atual:")
		-- "||" prints a literal "|"; without it the chat parses |H/|c as escapes
		print((BuildPayload():gsub("|", "||")))
	else
		Print("comandos: /dwow (liga/desliga), /dwow status")
	end
end
