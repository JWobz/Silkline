"""
banner_preview.py

Shows title designs for the silkline command in the terminal, with colours, so they
can be compared before one goes into silkline/style.py. Run it from the project root:

    python3 tools/banner_preview.py            # every design, in the red fade
    python3 tools/banner_preview.py 196        # every design in one 256-colour shade
    python3 tools/banner_preview.py colours    # all 256 colours with their numbers
    python3 tools/banner_preview.py 88 124 160 # the fade with these shades, top to bottom
    python3 tools/banner_preview.py shadows    # the shadow title in several red schemes
    python3 tools/banner_preview.py shadows 88 124 160 196 52   # your own: 4 shades + shadow
    python3 tools/banner_preview.py waves      # the sunset title with taller waves
    python3 tools/banner_preview.py waves 14   # the same, each wave step 14 wide
    python3 tools/banner_preview.py signal     # a wave that starts on a centre line
    python3 tools/banner_preview.py signal 18  # the same with wider steps
    python3 tools/banner_preview.py bars       # an audio waveform of bars (3 seeds, 2 heights)
    python3 tools/banner_preview.py bars 42    # one seed: try numbers until you like one
    python3 tools/banner_preview.py shapes     # 5 wave shapes, gaps and no gaps, random seed
    python3 tools/banner_preview.py shapes 1234 bursts   # one shape, a seed you liked
    python3 tools/banner_preview.py spikes     # the sound shape at 6 spike settings
    python3 tools/banner_preview.py spikes 1234          # the same, a seed you liked
    python3 tools/banner_preview.py lines      # the bars as lines that join between rows

The letters are drawn with half blocks (▀ ▄ █), 3 rows high; the wave under them is
a rule made of the 1/8 blocks (▁▂▃▄▅▆▇).
"""
import sys

# Each letter: 3 rows, all the same width within a letter.
LETTERS = {
    "S": ("█▀▀", "▀▀█", "▀▀▀"),
    "I": ("█", "█", "▀"),
    "L": ("█  ", "█  ", "▀▀▀"),
    "K": ("█ ▄▀", "█▀▄ ", "▀  ▀"),
    "N": ("█▄ █", "█ ▀█", "▀  ▀"),
    "E": ("█▀▀", "█▀▀", "▀▀▀"),
    " ": ("  ", "  ", "  "),
}

FADE = (160, 196, 203)          # one shade per row, darkest at the top
WAVE = "▁▂▃▅▆▅▃▂"               # one bump of the sound wave (repeats without a seam)

# Waves for terminals whose font lacks the 1/8 blocks: half blocks and plain text only.
WAVES = {
    "square": "▄▄▄▀▀▀",          # a square wave (what distortion looks like)
    "pulse": "▄▀",
    "zigzag": "▄▀▀▄",
    "ascii": "_.-~'~-.",
    "line": "─",
}


def word(text, gap=" "):
    """`text` in the block letters, as 3 lines."""
    rows = []
    for row in range(3):
        rows.append(gap.join(LETTERS[c][row] for c in text.upper()))
    return rows


# A bigger font as pixels ("#" on): 7 rows, 2-wide strokes. Two pixel rows go in one
# line of text (half blocks), so it's 4 lines tall.
PIXELS = {
    "S": (" #####", "##    ", "##    ", " #### ", "    ##", "    ##", "##### "),
    "I": ("##", "##", "##", "##", "##", "##", "##"),
    "L": ("##    ", "##    ", "##    ", "##    ", "##    ", "##    ", "######"),
    "K": ("##  ##", "## ## ", "####  ", "###   ", "####  ", "## ## ", "##  ##"),
    "N": ("##   ##", "###  ##", "#### ##", "## ####", "##  ###", "##   ##", "##   ##"),
    "E": ("######", "##    ", "##    ", "##### ", "##    ", "##    ", "######"),
}

SHADOW = 52                     # the drop shadow's shade (very dark red); 236 is dark grey


def pixel_word(text, gap=2, shadow=True):
    """`text` in PIXELS as a grid of cells: "L" letter, "S" shadow, " " empty."""
    rows = len(next(iter(PIXELS.values())))
    grid = ["" for _ in range(rows)]
    for i, c in enumerate(text.upper()):
        for r in range(rows):
            grid[r] += (" " * gap if i else "") + PIXELS[c][r]
    width = len(grid[0]) + 1
    cells = [[("L" if ch == "#" else " ") for ch in row.ljust(width)] for row in grid]
    cells.append([" "] * width)                        # room for the shadow under the last row
    if shadow:
        for r in range(rows, 0, -1):                   # the shadow: 1 right and 1 down
            for x in range(width - 1, 0, -1):
                if cells[r][x] == " " and cells[r - 1][x - 1] == "L":
                    cells[r][x] = "S"
    return cells


def render(cells, shades, shadow=SHADOW):
    """Pixel cells as coloured half-block lines: 2 pixel rows per line, the fade per line."""
    if len(cells) % 2:
        cells = cells + [[" "] * len(cells[0])]
    lines = []
    for n, r in enumerate(range(0, len(cells), 2)):
        colour = {"L": shades[min(n, len(shades) - 1)], "S": shadow}
        out = ""
        for top, bottom in zip(cells[r], cells[r + 1]):
            if top == bottom == " ":
                out += " "
            elif top == bottom:
                out += f"\033[38;5;{colour[top]}m█\033[0m"
            elif bottom == " ":
                out += f"\033[38;5;{colour[top]}m▀\033[0m"
            elif top == " ":
                out += f"\033[38;5;{colour[bottom]}m▄\033[0m"
            else:                                       # two colours: fg on top, bg below
                out += f"\033[38;5;{colour[top]};48;5;{colour[bottom]}m▀\033[0m"
        lines.append(" " + out)
    return lines


def wave_cells(width, lines=2, period=10, filled=False):
    """A square wave as pixel cells ("L" on), `lines` lines tall (2 pixel rows each).

    Outline: a line along the top while high and along the bottom while low, with a
    vertical edge at every change. Filled: solid while high, the bottom row while low.
    """
    rows = lines * 2
    cells = [[" "] * width for _ in range(rows)]
    for x in range(width):
        phase = x % period
        high = phase < period // 2
        edge = phase in (0, period // 2)
        for r in range(rows):
            if edge or (filled and high):
                on = True
            elif high:
                on = r == 0
            else:
                on = r == rows - 1
            if on:
                cells[r][x] = "L"
    return cells


def signal_cells(width, period=14, lead=None, rows=5, lead_out=False):
    """A square wave around a centre line, as pixel cells ("L" on).

    It starts flat on the middle row for `lead` columns (half a period if not given),
    then swings to the top row and the bottom row in turn, each for half a period; with
    `lead_out` it comes back to the middle for the last `lead` columns. Each change of
    level draws a vertical edge between the two levels. rows=5 gives top 0, middle 2,
    bottom 4: 3 lines of half blocks (the 6th pixel row is empty).
    """
    half = period // 2
    end = width
    if lead_out and lead is None:
        # Whole up-and-down swings only, with (nearly) the same flat part at each end.
        swings = (width - period) // period            # leave at least half a period each end
        lead = (width - swings * period) // 2
        end = lead + swings * period                   # where the swings stop
    elif lead_out:
        end = width - lead
    lead = half if lead is None else lead
    top, middle, bottom = 0, rows // 2, rows - 1
    levels = []
    for x in range(width):
        if x < lead or x >= end:
            levels.append(middle)
        else:
            levels.append(top if ((x - lead) // half) % 2 == 0 else bottom)
    cells = [[" "] * width for _ in range(rows + rows % 2)]
    for x, level in enumerate(levels):
        before = levels[x - 1] if x else level
        for r in range(min(before, level), max(before, level) + 1):
            cells[r][x] = "L"                     # the edge (or just the level, if it didn't change)
    return cells


def bar_heights(count, seed=7, smooth=0.5, spikes=0.15, spike_low=0.75, quiet=1.6):
    """`count` bar heights from 0 to 1, like an audio waveform: random, but smoothed so
    neighbours are related, with a slow swell across the width. The same seed always
    gives the same bars.

    spikes: the chance each bar is a spike; spike_low: a spike's shortest height (1.0
    makes every spike full height); quiet: how much the ordinary bars are pushed down
    (higher is quieter, so the spikes stand out more).
    """
    import math
    import random
    rnd = random.Random(seed)
    heights, last = [], 0.5
    for i in range(count):
        swell = 0.6 + 0.4 * math.sin(i / count * math.pi * 3 + seed)    # a few slow bumps
        last = smooth * last + (1 - smooth) * rnd.random()
        h = (last * swell) ** quiet                                      # quiet bars stay quiet
        if rnd.random() < spikes:
            h = spike_low + (1 - spike_low) * rnd.random()               # a tall spike
        heights.append(min(1.0, max(0.0, h)))
    return heights


# Spike settings to compare: (name, spikes, spike_low, quiet).
SPIKES = (
    ("now", 0.15, 0.75, 1.6),
    ("more spikes", 0.25, 0.75, 1.6),
    ("lots of spikes", 0.35, 0.7, 1.6),
    ("full-height spikes", 0.2, 1.0, 1.6),
    ("quiet bed, tall spikes", 0.2, 0.85, 2.6),
    ("very quiet bed, few spikes", 0.12, 0.9, 3.5),
)


def shaped_heights(count, shape, seed):
    """Bar heights from 0 to 1 in one of several shapes (see SHAPES), from a seed."""
    import math
    import random
    rnd = random.Random(seed)
    out = []
    if shape == "sound":
        return bar_heights(count, seed)
    for i in range(count):
        t = i / max(count - 1, 1)                     # 0 at the left, 1 at the right
        noise = rnd.random()
        if shape == "taper":                          # quiet at both ends, loud in the middle
            h = math.sin(t * math.pi) * (0.4 + 0.6 * noise)
        elif shape == "bursts":                       # words: loud bursts with quiet gaps
            burst = math.sin(t * math.pi * 5 + seed) > -0.2
            h = (0.35 + 0.65 * noise) if burst else 0.05 * noise
        elif shape == "beat":                         # drum hits that die away
            phase = (i % 8) / 8
            h = (1 - phase) ** 2 * (0.7 + 0.3 * noise)
        elif shape == "swell":                        # grows from left to right
            h = t ** 1.3 * (0.5 + 0.5 * noise)
        else:
            raise ValueError(shape)
        out.append(min(1.0, max(0.0, h)))
    return out


SHAPES = ("sound", "taper", "bursts", "beat", "swell")


def shaped_cells(width, rows, heights, gap):
    """Bars of the given heights, `gap` columns apart, mirrored around the centre line."""
    half = rows // 2
    cells = [[" "] * width for _ in range(rows)]
    for x, h in zip(range(0, width, gap + 1), heights):
        reach = round(h * (half - 1))
        for r in range(half - 1 - reach, half + 1 + reach):
            cells[r][x] = "L"
    return cells


def bars_cells(width, rows=8, seed=7, gap=1):
    """A waveform of vertical bars as pixel cells ("L" on), mirrored around the centre
    line. `rows` is even, so the centre falls between two lines of text and every bar
    is the same height above and below it: 8 rows is 4 lines, 10 is 5."""
    half = rows // 2
    cells = [[" "] * width for _ in range(rows)]
    columns = list(range(0, width, gap + 1))
    for x, h in zip(columns, bar_heights(len(columns), seed)):
        reach = round(h * (half - 1))                   # extra pixels beyond the shortest bar
        for r in range(half - 1 - reach, half + 1 + reach):
            cells[r][x] = "L"
    return cells


def double(lines):
    """`lines` of half blocks at twice the size: each character becomes 2 wide and 2 tall."""
    top = {"█": "██", "▀": "██", "▄": "  ", " ": "  "}
    bottom = {"█": "██", "▀": "  ", "▄": "██", " ": "  "}
    out = []
    for line in lines:
        out.append("".join(top[c] for c in line))
        out.append("".join(bottom[c] for c in line))
    return [row for row in out if row.strip()]        # the last ▀ row leaves an empty one


def box_wave(width, step=6):
    """A 2-row square wave in box lines: ┌───┐ on top, ┘   └ below, each step `step` wide."""
    # Starts low; each ┌ sits over a ┘ (the rising edge) and each ┐ over a └ (falling).
    high = " " * step + "┌" + "─" * (step - 2) + "┐"
    low = "─" * step + "┘" + " " * (step - 2) + "└"
    rows = []
    for pattern in (high, low):
        rows.append((pattern * (width // len(pattern) + 2))[:width])
    return rows


def wave(width, pattern=WAVE):
    """A sound-wave rule exactly `width` characters wide, repeating `pattern`."""
    return (pattern * (width // len(pattern) + 1))[:width]


def shade(n, text):
    return f"\033[38;5;{n}m{text}\033[0m"


def dim(text):
    return f"\033[90m{text}\033[0m"


def show(name, lines, shades):
    print(dim(f"── {name} " + "─" * 30))
    for line, n in zip(lines, shades):
        print(shade(n, line))
    print()


def designs(version="1.0.0"):
    """(name, lines) for each design; the last lines are the subtitle."""
    letters = word("silkline")
    width = len(letters[0])
    sub = f"v{version} · Line 6 Spider V MkII over USB"
    yield "A: blocks + wave", [" " + l for l in letters] + [" " + wave(width), " " + sub]
    for name, pattern in WAVES.items():
        yield f"A-{name}: blocks + {name} wave", [" " + l for l in letters] + [" " + wave(width, pattern), " " + sub]
    big = double(letters)
    bw = len(big[0])
    yield "D-blocks: double size, doubled square wave", [" " + l for l in big] + [" " + l for l in double([wave(width, WAVES["square"])])] + [" " + sub]
    yield "D-long: double size, long square wave", [" " + l for l in big] + [" " + wave(bw, "▄" * 6 + "▀" * 6), " " + sub]
    yield "D-box: double size, box-line square wave", [" " + l for l in big] + [" " + l for l in box_wave(bw)] + [" " + sub]
    yield "B: blocks, wide gap", [" " + l for l in word("silkline", "  ")] + ["", " " + sub]
    yield "C: one line", [f" ∿∿ SILKLINE  {sub}"]


def palette():
    """All 256 colours: the 16 basic ones, the 6x6x6 cube in rows of 36, then the greys."""
    def cell(n):
        return f"\033[48;5;{n}m  \033[0m{shade(n, f'{n:>3}')} "
    print(dim("basic 0-15 (the \\033[3Xm / \\033[9Xm colours)"))
    print("".join(cell(n) for n in range(16)))
    print(dim("\ncube 16-231"))
    for start in range(16, 232, 12):
        print("".join(cell(n) for n in range(start, start + 12)))
    print(dim("\ngreys 232-255"))
    for start in range(232, 256, 12):
        print("".join(cell(n) for n in range(start, start + 12)))
    print(dim('\nUse one as "\\033[38;5;Nm" (text) in silkline/style.py, e.g. ACCENT = "\\033[38;5;160m".'))


def show_pixel_designs(fade, version="1.0.0"):
    """The E designs: the bigger pixel font, with and without its shadow, and a wave."""
    sub = f"v{version} · Line 6 Spider V MkII over USB"
    for name, shadow in (("E-shadow: pixel font + drop shadow", True), ("E-flat: pixel font", False)):
        cells = pixel_word("silkline", shadow=shadow)
        width = len(cells[0])
        print(dim(f"── {name} " + "─" * 30))
        for line in render(cells, fade):
            print(line)
        print(shade(fade[len(fade) // 2], " " + wave(width, "▄" * 5 + "▀" * 5)))
        print(dim(" " + sub))
        print()


# Red schemes for the shadow title: (name, fade top to bottom, shadow).
SCHEMES = (
    ("ember (now)", (160, 196, 203, 210), 52),
    ("deep", (124, 160, 196, 203), 52),
    ("darker", (88, 124, 160, 196), 52),
    ("blood", (52, 88, 124, 160), 233),
    ("sunset (dark at the bottom)", (196, 160, 124, 88), 52),
    ("solid deep red", (124, 124, 124, 124), 52),
    ("solid red, grey shadow", (160, 160, 160, 160), 236),
    ("wine", (89, 125, 161, 168), 53),
    ("deep, black shadow", (124, 160, 196, 203), 232),
)


def show_schemes(version="1.0.0"):
    """The shadow title in each of SCHEMES, labelled with its numbers."""
    cells = pixel_word("silkline", shadow=True)
    width = len(cells[0])
    for name, fade, shadow in SCHEMES:
        print(dim(f"── {name}: fade {' '.join(map(str, fade))}, shadow {shadow} " + "─" * 10))
        for line in render(cells, fade, shadow):
            print(line)
        print(shade(fade[len(fade) // 2], " " + wave(width, "▄" * 5 + "▀" * 5)))
        print(dim(f" v{version} · Line 6 Spider V MkII over USB"))
        print()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["colours"] or args[:1] == ["colors"]:
        palette()
        sys.exit()
    if args[:1] == ["symbols"]:
        # Candidates for OK_MARK, BAD_MARK, BUSY_MARK and HERE_MARK in silkline/style.py,
        # numbered, so you can say which ones your terminal's font shows properly.
        marks = (("OK_MARK (worked)", "✓ ✔ √ + * ●"), ("BAD_MARK (error)", "✗ ✘ × x ! ■"),
                 ("BUSY_MARK (in progress)", "● • ◆ ○ * ~"), ("HERE_MARK (current row)", "▶ ► ▸ > » →"))
        n = 0
        for name, chars in marks:
            print(dim(name))
            row = []
            for c in chars.split():
                n += 1
                row.append(f"{dim(str(n) + ':')} {shade(196, c)}")
            print("   " + "    ".join(row))
            print()
        print(dim("Tell me the numbers that show as a symbol, not a box or ?"))
        sys.exit()
    if args[:1] == ["lines"]:
        # lines           the sound wave drawn with box-drawing lines instead of blocks
        # lines 1234      the same with a seed you liked
        # Box-drawing characters are made to join up between lines, so the bars don't
        # break where the terminal leaves space between lines of text.
        import random
        seed = int(args[1]) if len(args) > 1 else random.randrange(10000)
        fade, shadow = (196, 160, 124, 88), 52
        letters = pixel_word("silkline", shadow=True)
        width = len(letters[0])
        heights = bar_heights(len(range(0, width, 2)), seed, spikes=0.25)
        cells = shaped_cells(width, 10, heights, 1)
        styles = (("blocks (now)", "█▀▄"), ("heavy lines", "┃╹╻"), ("light lines", "│╵╷"),
                  ("heavy, light tips", "┃╵╷"))
        for name, (full, top, bottom) in styles:
            print(dim(f"── {name}, seed {seed} " + "─" * 30))
            print()
            for line in render(letters, fade, shadow):
                print(line)
            print()
            for line in render(cells, [88, 160, 196, 160, 88], shadow):
                print(line.replace("█", full).replace("▀", top).replace("▄", bottom))
            print(dim(" v1.0.0 · Line 6 Spider V MkII over USB"))
            print()
        print(dim(f"seed {seed}: run 'python3 tools/banner_preview.py lines {seed}' to see it again"))
        sys.exit()
    if args[:1] == ["spikes"]:
        # spikes          the sound shape (gaps) at each SPIKES setting, random seed
        # spikes 1234     the same with a seed you liked
        import random
        seed = int(args[1]) if len(args) > 1 else random.randrange(10000)
        fade, shadow = (196, 160, 124, 88), 52
        letters = pixel_word("silkline", shadow=True)
        width = len(letters[0])
        count = len(range(0, width, 2))
        for name, rate, low, quiet in SPIKES:
            heights = bar_heights(count, seed, spikes=rate, spike_low=low, quiet=quiet)
            print(dim(f"── {name}: spikes {rate}, spike_low {low}, quiet {quiet}, seed {seed} " + "─" * 6))
            print()
            for line in render(letters, fade, shadow):
                print(line)
            print()
            for line in render(shaped_cells(width, 10, heights, 1), [88, 160, 196, 160, 88], shadow):
                print(line)
            print(dim(" v1.0.0 · Line 6 Spider V MkII over USB"))
            print()
        print(dim(f"seed {seed}: run 'python3 tools/banner_preview.py spikes {seed}' to see it again"))
        sys.exit()
    if args[:1] == ["shapes"]:
        # shapes          every shape, with and without gaps, on a new random seed each run
        # shapes 1234     the same with a seed you liked
        # shapes 1234 bursts   one shape only
        import random
        seed = int(args[1]) if len(args) > 1 else random.randrange(10000)
        only = args[2:3]
        fade, shadow = (196, 160, 124, 88), 52
        letters = pixel_word("silkline", shadow=True)
        width = len(letters[0])
        for shape in (only or SHAPES):
            for gap in (1, 0):
                count = len(range(0, width, gap + 1))
                cells = shaped_cells(width, 10, shaped_heights(count, shape, seed), gap)
                print(dim(f"── {shape}, {'gaps' if gap else 'no gaps'}, seed {seed} " + "─" * 20))
                print()
                for line in render(letters, fade, shadow):
                    print(line)
                print()
                for line in render(cells, [88, 160, 196, 160, 88], shadow):
                    print(line)
                print(dim(" v1.0.0 · Line 6 Spider V MkII over USB"))
                print()
        print(dim(f"seed {seed}: run 'python3 tools/banner_preview.py shapes {seed}' to see it again"))
        sys.exit()
    if args[:1] == ["bars"]:
        # bars            three seeds, at two heights
        # bars 42         one seed, at both heights
        seeds = [int(args[1])] if len(args) > 1 else [7, 21, 42]
        fade, shadow = (196, 160, 124, 88), 52
        letters = pixel_word("silkline", shadow=True)
        width = len(letters[0])
        for seed in seeds:
            for rows, lines in ((8, 4), (10, 5)):
                # Brightest at the centre line, darker towards the tips (the sunset reds).
                if lines == 4:
                    shades = [124, 196, 196, 124]
                else:
                    shades = [88, 160, 196, 160, 88]
                print(dim(f"── bars: seed {seed}, {lines} lines " + "─" * 20))
                print()
                for line in render(letters, fade, shadow):
                    print(line)
                print()
                for line in render(bars_cells(width, rows, seed), shades, shadow):
                    print(line)
                print(dim(" v1.0.0 · Line 6 Spider V MkII over USB"))
                print()
        sys.exit()
    if args[:1] == ["signal"]:
        # The sunset title over a wave that starts on a centre line. signal 18   a wider step.
        period = int(args[1]) if len(args) > 1 else 14
        fade, shadow = (196, 160, 124, 88), 52
        letters = pixel_word("silkline", shadow=True)
        width = len(letters[0])
        for name, lead_out in (("starts in the middle", False), ("starts and ends in the middle", True)):
            print(dim(f"── signal: {name}, period {period} " + "─" * 20))
            print()
            for line in render(letters, fade, shadow):
                print(line)
            print()
            cells = signal_cells(width, period, lead_out=lead_out)
            for line in render(cells, [fade[1]] * 3, shadow):
                print(line)
            print(dim(" v1.0.0 · Line 6 Spider V MkII over USB"))
            print()
        sys.exit()
    if args[:1] == ["waves"]:
        # The sunset title with taller waves. waves 12   tries a period of 12 instead of 10.
        period = int(args[1]) if len(args) > 1 else 10
        fade, shadow = (196, 160, 124, 88), 52
        letters = pixel_word("silkline", shadow=True)
        width = len(letters[0])
        for name, lines, filled in (("1 line (now)", 1, False), ("2 lines, outline", 2, False),
                                    ("3 lines, outline", 3, False), ("2 lines, filled", 2, True),
                                    ("3 lines, filled", 3, True)):
            print(dim(f"── wave: {name}, period {period} " + "─" * 20))
            print()
            for line in render(letters, fade, shadow):
                print(line)
            print()
            if lines == 1:
                print(shade(fade[1], " " + wave(width, "▄" * (period // 2) + "▀" * (period // 2))))
            else:
                for line in render(wave_cells(width, lines, period, filled), [fade[1]] * lines, shadow):
                    print(line)
            print(dim(" v1.0.0 · Line 6 Spider V MkII over USB"))
            print()
        sys.exit()
    if args[:1] == ["shadows"]:
        # shadows                 every scheme in SCHEMES
        # shadows 88 124 160 196 52   your own: four fade shades, then the shadow
        if len(args) == 6:
            SCHEMES = (("yours", tuple(int(a) for a in args[1:5]), int(args[5])),)
        show_schemes()
        sys.exit()
    picked = [int(a) for a in args]
    show_pixel_designs(picked or [160, 196, 203, 210])
    for name, lines in designs():
        rows = 5 if name.startswith("D") else 3       # the letter rows; the rest is wave + subtitle
        fade = picked or list(FADE)
        if len(lines) == 1:
            rows = 1
        # Spread the fade over the letter rows (each shade covers rows/len(fade) of them).
        shades = [fade[min(i * len(fade) // rows, len(fade) - 1)] for i in range(rows)]
        wave_rows = len(lines) - rows - 1
        show(name, lines, shades + [fade[len(fade) // 2]] * wave_rows + [90])
    widths = [len(l) for l in word("silkline")]
    print(dim(f"letter rows are {widths} wide"))
