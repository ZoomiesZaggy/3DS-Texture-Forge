"""Title ID -> human-readable game name.

Hand-curated list -- v1 maintained the same dict in backend.py. Kept here
so both the CLI manifest and the GUI status pane can resolve title IDs.

Add new entries when their textures are validated against an Azahar dump.
"""

from __future__ import annotations


KNOWN_GAMES = {
    "0004000000060200": "Resident Evil: Revelations",
    "0004000000035D00": "Resident Evil: Revelations",
    "0004000000060100": "Resident Evil: Revelations",
    "0004000000194200": "Corpse Party",
    "0004000000055E00": "Pokemon Y",
    "0004000000055D00": "Pokemon X",
    "0004000000175E00": "Pokemon Omega Ruby",
    "000400000011C400": "Pokemon Omega Ruby",
    "000400000011C500": "Pokemon Alpha Sapphire",
    "0004000000175F00": "Pokemon Alpha Sapphire",
    "0004000000030800": "Mario Kart 7",
    "0004000000033500": "Zelda: Ocarina of Time 3D",
    "0004000000033400": "Zelda: Ocarina of Time 3D",
    "000400000008F900": "Zelda: Majora's Mask 3D",
    "000400000008F800": "Zelda: Majora's Mask 3D",
    "0004000000086400": "Animal Crossing: New Leaf",
    "0004000000086300": "Animal Crossing: New Leaf",
    "0004000000030600": "Super Mario 3D Land",
    "0004000000030500": "Super Mario 3D Land",
    "000400000007AE00": "New Super Mario Bros. 2",
}


def get_game_name(title_id: str, product_code: str = "") -> str:
    """Resolve a 16-char title ID to a friendly name.

    Falls back to the product code, then to a short title-ID slug.
    """
    tid = title_id.upper().replace("0X", "").zfill(16)
    if tid in KNOWN_GAMES:
        return KNOWN_GAMES[tid]
    if product_code:
        code = product_code.replace("CTR-P-", "").replace("CTR-N-", "")
        return f"Game {code}" if code else product_code
    return f"Game {tid[-8:]}"
