"""
knob.py

The preset knob: settling its position after a click (protocol.md section 11).
"""

POSITIONS = 16


def settle_position(candidates, previous):
    """Picks the real preset-knob position from the values seen during one click.

    The knob's contacts bounce, and a stray reading is the 4-bit complement of a real
    one (see protocol.md section 11). So each candidate could also be its complement.
    A single click moves one step, so prefer a position one step from `previous`.
    Falls back to the last candidate when that doesn't settle it.
    """
    if not candidates:
        return previous
    if previous is None:
        return candidates[-1]
    for position in reversed(candidates):
        for option in (position, _complement_position(position)):
            if (option - previous) % POSITIONS in (1, POSITIONS - 1):
                return option
    return candidates[-1]


def _complement_position(position):
    """The position a bounced reading of `position` would give (raw value XOR 0x0F)."""
    raw = (position + 8) % POSITIONS
    return ((raw ^ 0x0F) - 8) % POSITIONS

def find_slot(name, presets, last_position):
    """The slot (0 to 15) the knob loaded, or None if it can't be told."""
    matches = [n for n in range(POSITIONS) if presets.get(n) == name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) < 2 or last_position is None:
        return None     
    slot = (last_position + 8) % POSITIONS
    options = [s for s in (slot, slot ^ 0x0F) if s in matches]
    if len(options) == 1:
        return options[0]
    else:
        return None 