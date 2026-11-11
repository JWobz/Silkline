"""
style.py

Colours and symbols for the silkline command (cli.py), all in one place.

The colours are named by meaning (GOOD, BAD, BUSY, DIM, ACCENT), so changing one
variable restyles everything that means it. They are ANSI escape codes:
"\033[" + a number + "m" (31 red, 32 green, 33 yellow, 36 cyan, 90 grey; 1 bold,
combined with ";", e.g. "\033[1;36m"). Text is only coloured in a real terminal
and never when NO_COLOR is set (no-color.org), so pipes, files and the tests get
plain text.

banner() draws the start-up title: SILKLINE in a pixel font (PIXELS, 7 rows, two
per line of half blocks) with a drop shadow, the version at its bottom right, and
an audio-style waveform underneath (bars mirrored around a centre line, a new
shape each run unless BANNER_SEED is set). Its look is the BANNER_ variables;
tools/banner_preview.py tries out other settings.
"""

import math
import os
import random
import sys

PIXELS = {
    "S": (" #####", "##    ", "##    ", " #### ", "    ##", "    ##", "##### "),
    "I": ("##", "##", "##", "##", "##", "##", "##"),
    "L": ("##    ", "##    ", "##    ", "##    ", "##    ", "##    ", "######"),
    "K": ("##  ##", "## ## ", "####  ", "###   ", "####  ", "## ## ", "##  ##"),
    "N": ("##   ##", "###  ##", "#### ##", "## ####", "##  ###", "##   ##", "##   ##"),
    "E": ("######", "##    ", "##    ", "##### ", "##    ", "##    ", "######"),
}

LABEL_WIDTH = 18
METER_WIDTH = 10                           # blocks in a meter
METER_FULL, METER_EMPTY = "█", "·"         # · rather than ░: it shows in your terminal

BANNER_SEED = None                         # None: a new wave every run; a number: always that one
BANNER_SPIKES = 0.35                       # the chance each bar is a spike
BANNER_SPIKE_LOW = 0.7                     # a spike's shortest height (1.0: every spike full height)
BANNER_QUIET = 1.6                         # higher pushes the ordinary bars down
BANNER_SHADOW = 52                         # the drop shadow: very dark red
BANNER_WAVE_ROWS = 8                       # pixel rows (2 per line): 10 is 5 lines
BANNER_WAVE_FADE = (124, 196, 196, 124)    # one shade per line: brightest at the centre
BANNER_FADE = (196, 160, 124, 88)          # sunset: one shade per letter line, top to bottom

ACCENT = "\033[38;5;160m"            # deep red: the prompt, the selected row
BAD = "\033[1;38;5;196m"             # bold bright red: errors
GOOD = "\033[32m"                   # green: connected, saved, on
BUSY = "\033[33m"                   # yellow: connecting, saving
DIM = "\033[90m"                    # grey: timestamps, labels, preset numbers
RESET = "\033[0m"                   # back to normal: ends every coloured piece

OK_MARK, BAD_MARK, BUSY_MARK, HERE_MARK = "√", "×", "•", "►"


def _pixels(text, gap=2):
    """`text` in PIXELS as rows of cells: "L" letter, "S" shadow, " " empty."""
    grid = ["", "", "", "", "", "", ""]
    for i, c in enumerate(text.upper()):
        for r in range(7):
            grid[r] += (" " * gap if i else "") + PIXELS[c][r]
    width = len(grid[0]) + 1
    cells = [[("L" if ch == "#" else " ") for ch in row.ljust(width)] for row in grid]
    cells.append([" "] * width)
    for r in range(7, 0, -1):
        for x in range(width - 1, 0, -1):
            if cells[r][x] == " " and cells[r - 1][x - 1] == "L":
                cells[r][x] = "S"
    return cells

def _render(cells, fade=None):
    """The cells as coloured half-block lines: 2 pixel rows per line, one shade of
    `fade` per line (BANNER_FADE if not given), shadow cells in BANNER_SHADOW.

    A cell with letter on top and shadow below (or the reverse) is one ▀ with two
    colours: the text colour (38;5) paints its top half, the background (48;5) the
    bottom half. The fade is read on each call, so changing BANNER_FADE takes effect.
    """
    fade = fade or BANNER_FADE
    lines = []
    for n, r in enumerate(range(0, len(cells), 2)):
        colour = {"L": fade[min(n, len(fade) - 1)], "S": BANNER_SHADOW}
        out = ""
        for top, bottom in zip(cells[r], cells[r + 1]):
            if top == bottom == " ":
                out += " "
            elif top == bottom:
                out += f"{shade(colour[top])}█{RESET}"
            elif bottom == " ":
                out += f"{shade(colour[top])}▀{RESET}"
            elif top == " ":
                out += f"{shade(colour[bottom])}▄{RESET}"
            else:
                out += f"\033[38;5;{colour[top]};48;5;{colour[bottom]}m▀{RESET}" 

        lines.append(" " + out)
    return lines

def _bar_heights(count, seed):
    """`count` bar heights from 0 to 1, like an audio waveform.

    Random but smoothed (each bar half the last one, half new), with a few slow swells
    across the width; BANNER_QUIET pushes the ordinary bars down, and BANNER_SPIKES of
    them are spikes at least BANNER_SPIKE_LOW tall. random.Random(seed) is its own
    generator: the same seed always gives the same heights.
    """
    rnd = random.Random(seed)
    heights, last = [], 0.5
    for i in range(count):
        swell = 0.6 + 0.4 * math.sin(i / count * math.pi * 3 + seed)
        last = 0.5 * last + 0.5 * rnd.random()
        h = (last * swell) ** BANNER_QUIET
        if rnd.random() < BANNER_SPIKES:
            h = BANNER_SPIKE_LOW + (1 - BANNER_SPIKE_LOW) * rnd.random()
        heights.append(min(1.0, max(0.0, h)))
    return heights

def _bar_cells(width, seed):
    """The waveform as pixel cells ("L" on), BANNER_WAVE_ROWS tall: bars one column
    wide with a gap between, mirrored around the centre line (between rows half - 1
    and half), so the shortest bar is the two pixels either side of it.
    """
    half = BANNER_WAVE_ROWS // 2
    cells = [[" "] * width for _ in range(BANNER_WAVE_ROWS)]
    columns = range(0, width, 2)
    for x, h in zip(columns, _bar_heights(len(columns), seed)):
        reach = round(h * (half - 1))
        for r in range(half - 1 - reach, half + 1 + reach):
            cells[r][x] = "L"
    return cells

def banner(version):
    """The start-up title, with a blank line above and below.

    The letters with their shadow (BANNER_FADE, BANNER_SHADOW), the version at the end
    of their bottom line, a blank line, then the waveform (BANNER_WAVE_FADE), from
    BANNER_SEED or, if that is None, a new random seed. Without colour it is one plain
    line, since the shadow and bars only make sense in colour.
    """
    if not _colour_on():
        return f"\n SILKLINE v{version}\n"
    cells = _pixels("silkline")
    seed = BANNER_SEED if BANNER_SEED is not None else random.randrange(10000)
    bars = _render(_bar_cells(len(cells[0]), seed), BANNER_WAVE_FADE)
    letters = _render(cells)
    bars[-1] += "  " + dim(f"v{version}")
    return "\n" + "\n".join(letters + [""] + bars) + "\n"

def label(text):
    """`text` as a dim label, padded so the values after it line up."""
    return dim(text.ljust(LABEL_WIDTH))

def shade(n):
    """The escape code for 256-colour shade n (see: python3 tools/banner_preview.py colours)."""
    return f"\033[38;5;{n}m"

def meter(value):
    """A bar for a value from 0 to 1: METER_WIDTH blocks, the filled part in ACCENT."""
    filled = round(value * METER_WIDTH)
    return accent(METER_FULL * filled) + dim(METER_EMPTY * (METER_WIDTH - filled))

def _colour_on():
    """Colour only in a real terminal, and never when NO_COLOR is set."""
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ

def prompt_paint(colour, text):
    """Like paint(), but safe in a readline prompt: the codes are wrapped in \\001 and \\002."""
    if not _colour_on():
        return text
    return f"\001{colour}\002{text}\001{RESET}\002"

def paint(colour, text):
    """`text` in `colour` (one of the variables above), or plain when colour is off."""
    if not _colour_on():
        return text
    return f"{colour}{text}{RESET}"

def good(text):
    """Something worked: connected, saved, on."""
    return paint(GOOD, text)

def bad(text):
    """Errors and disconnects."""
    return paint(BAD, text)

def busy(text):
    """In progress: connecting, saving."""
    return paint(BUSY, text)

def dim(text):
    """Less important: timestamps, labels, preset numbers."""
    return paint(DIM, text)

def accent(text):
    """The prompt, the selected row, the banner."""
    return paint(ACCENT, text)