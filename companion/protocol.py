"""Generated protocol constants. Do not edit by hand.
Run: python tools/generate_protocol.py
"""

PROTOCOL_VERSION = 1
CELL_PX = 3
CELLS_PER_ROW = 128
MAX_PAYLOAD_BYTES = 600
MAGIC_A = (192, 255, 238)
MAGIC_B = (13, 21, 234)
REQUIRED_FIELD_COUNT = 16

FIELDS = [
    'name',
    'realm',
    'class_token',
    'class_name',
    'race',
    'level',
    'zone',
    'subzone',
    'instance_name',
    'instance_type',
    'hp_pct',
    'dead',
    'xp_pct',
    'group_size',
    'group_max',
    'guild',
]

OPTIONAL_FIELDS = [
    'race_token',
    'gender',
    'flags',
    'target',
    'target_hp',
    'target_class',
    'money',
    'faction',
    'form',
    'form_id',
    'activity',
    'difficulty',
    'target_level',
    'mount_spell',
    'mount_name',
]

ALL_FIELDS = FIELDS + OPTIONAL_FIELDS

FLAG_TAXI = 1
FLAG_COMBAT = 2
FLAG_RESTING = 4
FLAG_MOUNTED = 8
FLAG_SWIMMING = 16
FLAG_AFK = 32
FLAG_GHOST = 64
FLAG_STEALTH = 128
FLAG_FLYING = 256
FLAG_FALLING = 512
FLAG_FISHING = 1024
