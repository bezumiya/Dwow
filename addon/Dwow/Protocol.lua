-- Generated protocol constants. Do not edit by hand.
-- Run: python tools/generate_protocol.py
local _, ns = ...

ns.PROTOCOL = {
    VERSION = 1,
    CELL_PX = 3,
    CELLS_PER_ROW = 128,
    MAX_PAYLOAD_BYTES = 600,
    MAGIC_A = { 192, 255, 238 },
    MAGIC_B = { 13, 21, 234 },
    FLAGS = {
        TAXI = 1,
        COMBAT = 2,
        RESTING = 4,
        MOUNTED = 8,
        SWIMMING = 16,
        AFK = 32,
        GHOST = 64,
        STEALTH = 128,
        FLYING = 256,
        FALLING = 512,
        FISHING = 1024,
    },
    FIELD_LIMITS = {
        [1] = 36,
        [2] = 40,
        [4] = 30,
        [5] = 30,
        [7] = 60,
        [8] = 60,
        [9] = 60,
        [16] = 48,
        [20] = 48,
        [25] = 40,
        [27] = 80,
        [31] = 48,
    },
}
