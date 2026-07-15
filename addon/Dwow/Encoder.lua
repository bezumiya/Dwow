-- Encoder.lua — draws the payload as colored cells in the top-left corner.
-- Protocol constants come from Protocol.lua (generated from protocol/schema.json).

local ADDON, ns = ...

local P = ns.PROTOCOL
local CELL_PX = P.CELL_PX
local CELLS_PER_ROW = P.CELLS_PER_ROW
local PROTOCOL_VERSION = P.VERSION
local MAX_PAYLOAD_BYTES = P.MAX_PAYLOAD_BYTES
local MAGIC_A, MAGIC_B = P.MAGIC_A, P.MAGIC_B

local MOD_ADLER = 65521

-- Adler-32 truncated to 24 bits (same result as zlib.adler32(s) & 0xFFFFFF).
-- Simple arithmetic only: nothing here overflows Lua's double precision.
function ns.Adler24(s)
	local a, b = 1, 0
	for i = 1, #s do
		a = (a + s:byte(i)) % MOD_ADLER
		b = (b + a) % MOD_ADLER
	end
	return (b % 256) * 65536 + a
end

local strip
local cells = {}
local seq = 0

-- Makes 1 UI unit of the strip correspond to exactly 1 physical pixel,
-- whatever the player's UI scale: the WoW screen is always 768 units
-- tall at effective scale 1.
local function PixelScale()
	local _, physHeight = GetPhysicalScreenSize()
	return 768 / physHeight
end

function ns.RescaleStrip()
	if strip then
		strip:SetScale(PixelScale())
	end
end

local function EnsureStrip()
	if strip then return end
	-- Parented to WorldFrame to stay visible if the player hides the UI (Alt+Z).
	strip = CreateFrame("Frame", "DwowStrip", WorldFrame)
	strip:SetFrameStrata("TOOLTIP")
	if strip.SetIgnoreParentScale then
		strip:SetIgnoreParentScale(true)
	end
	strip:SetPoint("TOPLEFT", WorldFrame, "TOPLEFT", 0, 0)
	strip:SetSize(CELL_PX, CELL_PX)
	ns.RescaleStrip()
end

local function EnsureCells(n)
	for i = #cells + 1, n do
		local t = strip:CreateTexture(nil, "OVERLAY")
		t:SetSize(CELL_PX, CELL_PX)
		local col = (i - 1) % CELLS_PER_ROW
		local row = math.floor((i - 1) / CELLS_PER_ROW)
		t:SetPoint("TOPLEFT", strip, "TOPLEFT", col * CELL_PX, -row * CELL_PX)
		cells[i] = t
	end
end

local function SetCell(i, r, g, b)
	cells[i]:SetColorTexture(r / 255, g / 255, b / 255, 1)
	cells[i]:Show()
end

function ns.Draw(payload)
	EnsureStrip()
	if #payload > MAX_PAYLOAD_BYTES then
		payload = payload:sub(1, MAX_PAYLOAD_BYTES)
	end
	seq = (seq + 1) % 256

	local len = #payload
	local ck = ns.Adler24(payload)
	local total = 5 + math.ceil(len / 3)
	EnsureCells(total)

	SetCell(1, MAGIC_A[1], MAGIC_A[2], MAGIC_A[3])
	SetCell(2, MAGIC_B[1], MAGIC_B[2], MAGIC_B[3])
	SetCell(3, PROTOCOL_VERSION, len % 256, math.floor(len / 256))
	SetCell(4, seq, 0, 0)
	SetCell(5, math.floor(ck / 65536) % 256, math.floor(ck / 256) % 256, ck % 256)

	local ci = 6
	for i = 1, len, 3 do
		SetCell(ci, payload:byte(i), payload:byte(i + 1) or 0, payload:byte(i + 2) or 0)
		ci = ci + 1
	end
	for i = total + 1, #cells do
		cells[i]:Hide()
	end

	local rows = math.floor((total - 1) / CELLS_PER_ROW) + 1
	strip:SetSize(math.min(total, CELLS_PER_ROW) * CELL_PX, rows * CELL_PX)
end

function ns.SetStripShown(shown)
	EnsureStrip()
	strip:SetShown(shown)
end
