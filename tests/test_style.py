"""The colours (silkline/style.py): colour only in a real terminal and without NO_COLOR,
and every helper using its variable, so changing a variable restyles everything.
"""
import io
import os
import unittest
from unittest import mock

from silkline import style


class Terminal(io.StringIO):
    """ A stdout that says it's a terminal. """
    def isatty(self):
        return True


def in_terminal(env=None):
    """ Patches for a real terminal, with `env` as the environment. """
    return (mock.patch("sys.stdout", Terminal()),
            mock.patch.dict(os.environ, env or {}, clear=True))


class TestWhenToColour(unittest.TestCase):
    def test_plain_when_not_a_terminal(self):
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(style.good("ok"), "ok")

    def test_coloured_in_a_terminal(self):
        out, env = in_terminal()
        with out, env:
            self.assertEqual(style.good("ok"), f"{style.GOOD}ok{style.RESET}")

    def test_no_color_turns_it_off(self):
        out, env = in_terminal({"NO_COLOR": "1"})
        with out, env:
            self.assertEqual(style.bad("no"), "no")


class TestHelpers(unittest.TestCase):
    def test_each_helper_uses_its_variable(self):
        pairs = {style.good: "GOOD", style.bad: "BAD", style.busy: "BUSY",
                 style.dim: "DIM", style.accent: "ACCENT"}
        out, env = in_terminal()
        with out, env:
            for helper, name in pairs.items():
                with self.subTest(helper=helper.__name__):
                    self.assertEqual(helper("x"), getattr(style, name) + "x" + style.RESET)

    def test_changing_a_variable_changes_the_colour(self):
        out, env = in_terminal()
        with out, env, mock.patch.object(style, "BAD", "\033[35m"):
            self.assertTrue(style.bad("x").startswith("\033[35m"))

    def test_every_coloured_piece_is_reset(self):
        out, env = in_terminal()
        with out, env:
            self.assertTrue(style.dim("x").endswith(style.RESET))


def plain(text):
    """ `text` without its colour codes. """
    import re
    return re.sub(r"\033\[[0-9;]*m", "", text)


class TestBanner(unittest.TestCase):
    # Layout, by line: 0 blank, 1-4 letters, 5 blank, 6-9 the bars (the version at the
    # end of 9), 10 blank.
    LETTERS, BARS, VERSION = slice(1, 5), slice(6, 10), 9

    def coloured(self, seed=7):
        out, env = in_terminal()
        with out, env, mock.patch.object(style, "BANNER_SEED", seed):
            return style.banner("1.0.0")

    def lines(self, seed=7):
        return [plain(line) for line in self.coloured(seed).split("\n")]

    def test_plain_without_colour(self):
        with mock.patch("sys.stdout", io.StringIO()):
            text = style.banner("1.0.0")
        self.assertIn("1.0.0", text)
        self.assertNotIn("\033", text)
        self.assertEqual([line for line in text.split("\n") if line.strip()], [" SILKLINE v1.0.0"])

    def test_the_layout(self):
        lines = self.lines()
        self.assertEqual(len(lines), 11, lines)
        for i in (0, 5, 10):
            self.assertEqual(lines[i].strip(), "", f"line {i} should be blank")

    def test_the_version_is_at_the_bottom_right_of_the_bars(self):
        lines = self.lines()
        self.assertTrue(lines[self.VERSION].endswith("  v1.0.0"), lines[self.VERSION])
        self.assertEqual(sum("1.0.0" in line for line in lines), 1)    # only there
        self.assertNotIn("Spider", "\n".join(lines))

    def test_the_rows_line_up(self):
        lines = self.lines()
        bars = lines[self.BARS]
        bars[-1] = bars[-1][: -len("  v1.0.0")]                         # without the version
        rows = lines[self.LETTERS] + bars
        self.assertEqual(len({len(line) for line in rows}), 1, [len(line) for line in rows])

    def test_uses_the_fade_and_the_shadow(self):
        text = self.coloured()
        for n in style.BANNER_FADE + style.BANNER_WAVE_FADE:
            self.assertIn(f"38;5;{n}m", text)
        self.assertIn(f"48;5;{style.BANNER_SHADOW}m", text)  # the two-colour cells

    def test_changing_the_fade_changes_the_letters(self):
        with mock.patch.object(style, "BANNER_FADE", (21, 27, 33, 39)):
            letters = "\n".join(self.coloured().split("\n")[self.LETTERS])
        self.assertIn("38;5;21m", letters)
        self.assertNotIn("38;5;196m", letters)


class TestBars(unittest.TestCase):
    """ The waveform under the title (_bar_heights, _bar_cells, BANNER_SEED). """

    def test_the_same_seed_gives_the_same_bars(self):
        self.assertEqual(style._bar_cells(57, 7), style._bar_cells(57, 7))

    def test_different_seeds_give_different_bars(self):
        self.assertNotEqual(style._bar_cells(57, 7), style._bar_cells(57, 8))

    def test_no_seed_is_random_each_run(self):
        out, env = in_terminal()
        with out, env, mock.patch.object(style, "BANNER_SEED", None):
            banners = {style.banner("1.0.0") for _ in range(5)}
        self.assertGreater(len(banners), 1)

    def test_every_bar_is_mirrored_around_the_centre(self):
        cells = style._bar_cells(57, 7)
        rows = len(cells)
        for x in range(57):
            column = [cells[r][x] for r in range(rows)]
            self.assertEqual(column, column[::-1], f"column {x}")

    def test_every_bar_crosses_the_centre(self):
        cells = style._bar_cells(57, 7)
        half = style.BANNER_WAVE_ROWS // 2
        for x in range(0, 57, 2):
            self.assertEqual((cells[half - 1][x], cells[half][x]), ("L", "L"), f"column {x}")

    def test_gaps_between_bars(self):
        cells = style._bar_cells(57, 7)
        for x in range(1, 57, 2):
            self.assertTrue(all(row[x] == " " for row in cells), f"column {x} should be a gap")

    def test_heights_stay_between_0_and_1(self):
        for seed in range(50):
            heights = style._bar_heights(29, seed)
            self.assertTrue(all(0 <= h <= 1 for h in heights), seed)

    def test_more_spikes_means_more_tall_bars(self):
        def tall(rate):
            with mock.patch.object(style, "BANNER_SPIKES", rate):
                return sum(h >= style.BANNER_SPIKE_LOW for s in range(20) for h in style._bar_heights(29, s))
        self.assertGreater(tall(0.6), tall(0.1))

    def test_every_letter_has_seven_rows_of_one_width(self):
        for letter, rows in style.PIXELS.items():
            with self.subTest(letter=letter):
                self.assertEqual(len(rows), 7)
                self.assertEqual(len({len(r) for r in rows}), 1)


class TestLabelAndMeter(unittest.TestCase):
    def test_a_label_is_padded_to_label_width(self):
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(style.label("knob"), "knob".ljust(style.LABEL_WIDTH))

    def test_a_label_is_padded_before_it_is_coloured(self):
        out, env = in_terminal()
        with out, env:
            text = style.label("knob")
        self.assertEqual(plain(text), "knob".ljust(style.LABEL_WIDTH))

    def test_the_meter(self):
        with mock.patch("sys.stdout", io.StringIO()):
            cases = {0.0: 0, 0.55: 6, 1.0: 10, 0.04: 0, 0.96: 10}
            for value, filled in cases.items():
                with self.subTest(value=value):
                    bar = style.meter(value)
                    self.assertEqual(len(bar), style.METER_WIDTH)
                    self.assertEqual(bar.count(style.METER_FULL), filled)

    def test_the_meter_in_colour(self):
        out, env = in_terminal()
        with out, env:
            bar = style.meter(0.5)
        self.assertIn(style.ACCENT, bar)
        self.assertEqual(plain(bar), "█" * 5 + "·" * 5)


class TestPromptPaint(unittest.TestCase):
    def test_codes_are_wrapped_for_readline(self):
        out, env = in_terminal()
        with out, env:
            text = style.prompt_paint(style.ACCENT, "silkline")
        self.assertEqual(text, f"\001{style.ACCENT}\002silkline\001{style.RESET}\002")

    def test_plain_without_colour(self):
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(style.prompt_paint(style.ACCENT, "silkline"), "silkline")


if __name__ == "__main__":
    unittest.main()
