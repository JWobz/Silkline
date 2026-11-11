"""The silkline command (silkline/cli.py): the prompt's commands, and main()'s start-up,
with a fake service, so no amp is needed.

FakeService stands in for AmpService: it keeps the on_change callbacks, and
keep_connected() sends them the events a real connect would (or none, for an amp that
never answers).
"""
import io
import os
import threading
import unittest
from unittest import mock

import silkline
from silkline import cli, style
from silkline.logger import Logger
from silkline.protocol.parameters import BY_NAME, PARAMETERS
from silkline.state import AmpState, ConnectionState, Event, EventType


class FakeService:
    """ The parts of AmpService the command uses. """

    def __init__(self, connects=True):
        self.connects = connects
        self.callbacks = []
        self.stopped = False
        self._state = AmpState()
        self.values = {}
        self.sets = []

    def on_change(self, callback):
        self.callbacks.append(callback)

    def emit(self, event_type, **data):
        for callback in self.callbacks:
            callback(Event(event_type, data))

    def keep_connected(self):
        # Like the real one: returns at once, and connects on another thread. An amp
        # that never connects just reports one failed try, straight away.
        def connect():
            self.emit(EventType.CONNECTION_CHANGED, state=ConnectionState.CONNECTING)
            self._state.connection = ConnectionState.CONNECTED
            self.emit(EventType.CONNECTION_CHANGED, state=ConnectionState.CONNECTED)
            self.emit(EventType.PRESET_CHANGED, number=4, name="Chime 1: Class-A")
        if self.connects:
            threading.Thread(target=connect, daemon=True).start()
        else:
            self.emit(EventType.CONNECTION_CHANGED, state=ConnectionState.CONNECTING)
            self.emit(EventType.CONNECTION_CHANGED, state=ConnectionState.DISCONNECTED,
                      error="AmpNotFound('Could not find amp port.')")

    def state(self):
        return self._state

    def stop(self):
        self.stopped = True

    # Presets, like the real service: select_preset() checks the number, loads it,
    # and returns its name.
    PRESETS = {4: "Chime 1: Class-A", 5: "Chime 2: Drive", 8: "Jungle $lash", 20: "Metal Zone"}

    def presets(self):
        return dict(self.PRESETS)

    def select_preset(self, n):
        if n not in self.PRESETS:
            raise ValueError(f"no preset {n}")
        self.selected = n
        self._state.preset_number, self._state.preset_name = n, self.PRESETS[n]
        return self.PRESETS[n]

    # Parameters, by lower-case name, checked against the real list like the real
    # service does (unknown name, unsettable, out of range: ValueError).
    def get(self, name):
        if name.lower() not in BY_NAME:
            raise ValueError("Cannot find parameter to get")
        return self.values.get(name.lower())

    def set(self, name, value):
        param = BY_NAME.get(name.lower())
        if param is None:
            raise ValueError("Cannot find parameter to set")
        if not param.settable:
            raise ValueError(f"{param.name} can't be set")
        param.encode(value)
        self.values[name.lower()] = value
        self.sets.append((name.lower(), value))

    def save(self):
        if self._state.preset_number is None:
            raise ValueError("no slot")
        self.saved = self._state.preset_number
        return self._state.preset_name


def run(lines, service=None):
    """ main() with `lines` typed at the prompt and a fake service; returns (output, service). """
    service = service or FakeService()
    out = io.StringIO()
    with mock.patch.object(cli, "AmpService", return_value=service), \
            mock.patch("sys.stdin", io.StringIO("".join(line + "\n" for line in lines))), \
            mock.patch("sys.stdout", out), \
            mock.patch.object(Logger, "enabled", True):      # main() turns it off: undo after
        cli.main()
        enabled = Logger.enabled
    return out.getvalue(), service, enabled


def shell(service=None):
    """ A Shell on a fake service, writing to a StringIO (shell.stdout). """
    sh = cli.Shell(service or FakeService())
    sh.stdout = io.StringIO()
    return sh


class TestLeaving(unittest.TestCase):
    def test_exit_and_quit_end_the_prompt(self):
        for command in ("exit", "quit", "EOF"):
            with self.subTest(command=command):
                with mock.patch("sys.stdout", io.StringIO()):
                    self.assertTrue(shell().onecmd(command))

    def test_an_empty_line_does_nothing(self):
        # cmd's default would repeat the last command: dangerous after a set.
        sh = shell()
        sh.lastcmd = "exit"
        self.assertFalse(sh.onecmd(""))

    def test_an_unknown_command_doesnt_end_it(self):
        sh = shell()
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertFalse(sh.onecmd("frobnicate"))


def say(command, service=None):
    """ Run one command on a Shell; returns (what it printed, the service). """
    service = service or FakeService()
    out = io.StringIO()
    with mock.patch("sys.stdout", out):
        cli.Shell(service).onecmd(command)
    return out.getvalue(), service


def assert_usage(test, command, hint):
    """ `command` shows `hint` as a quiet usage hint: no error mark, nothing sent. """
    out, service = say(command)
    test.assertIn(hint, out)
    test.assertNotIn(style.BAD_MARK, out)
    test.assertEqual(service.sets, [])


class TestErrors(unittest.TestCase):
    def test_usage_hints_are_quiet_and_real_errors_are_marked(self):
        hint, _ = say("get")
        error, _ = say("get banjo")
        self.assertNotIn(style.BAD_MARK, hint)
        self.assertTrue(error.startswith(style.BAD_MARK + " "), error)
        self.assertNotIn("Error:", error)                       # the mark says it already

    def test_a_value_error_is_printed_not_raised(self):
        service = FakeService()
        service.select_preset = mock.Mock(side_effect=ValueError("bad preset"))
        out, _ = say("preset 3", service)
        self.assertIn(style.BAD_MARK, out)
        self.assertIn("bad preset", out)

    def test_an_amp_error_is_printed_not_raised(self):
        service = FakeService()
        service.select_preset = mock.Mock(side_effect=silkline.AmpDisconnected("not connected"))
        out, _ = say("preset 3", service)
        self.assertIn(style.BAD_MARK, out)
        self.assertIn("not connected", out)

    def test_the_prompt_keeps_going_after_an_error(self):
        out, _, _ = run(["preset 999", "presets jungle", "exit"])
        self.assertIn(style.BAD_MARK, out)
        self.assertIn("Jungle $lash", out)


class TestStatus(unittest.TestCase):
    def test_nothing_known_yet(self):
        out, _ = say("status")
        self.assertIn("disconnected", out)
        self.assertIn("not known", out)

    def test_everything_known(self):
        service = FakeService()
        s = service._state
        s.connection = ConnectionState.CONNECTED
        s.preset_number, s.preset_name, s.knob_position, s.bpm = 8, "Jungle $lash", 3, 120.0
        out, _ = say("status", service)
        for text in ("connected", "Jungle $lash", "#8", "3", "120"):
            with self.subTest(text=text):
                self.assertIn(text, out)
        self.assertNotIn("error", out)
        self.assertNotIn("slot not known", out)

    def test_an_unknown_slot_says_what_to_do(self):
        service = FakeService()
        service._state.preset_name = "Chime 1: Class-A"
        out, _ = say("status", service)
        line = [line for line in out.splitlines() if "Chime" in line][0]
        self.assertIn("slot not known", line)
        self.assertNotIn("#-", out)


class TestPresets(unittest.TestCase):
    MANY = {n: f"Preset {n}" for n in range(30)}

    def show(self, columns, presets=None, current=None, arg=""):
        """ presets in a terminal `columns` wide: the output's non-blank lines. """
        service = FakeService()
        if presets is not None:
            service.PRESETS = dict(presets)
        service._state.preset_number = current
        size = os.terminal_size((columns, 24))
        with mock.patch("shutil.get_terminal_size", return_value=size):
            out, _ = say(f"presets {arg}".strip(), service)
        return [line for line in out.splitlines() if line.strip()]

    def test_one_column_in_order(self):
        lines = self.show(30)
        names = list(FakeService.PRESETS.values())
        self.assertEqual(len(lines), len(names))
        for line, name in zip(lines, names):
            self.assertIn(name, line)

    def test_every_preset_once(self):
        text = "\n".join(self.show(200, self.MANY))
        for n in range(30):
            self.assertEqual(text.count(f"#{n} "), 1, n)

    def test_columns_read_downwards(self):
        lines = self.show(100, self.MANY)
        rows = len(lines)
        self.assertLess(rows, 30)                                # more than one column
        first = lines[0].split()
        self.assertEqual((first[0], first[3]), ("#0", f"#{rows}"))   # row 0: preset 0, then preset `rows`

    def test_the_columns_line_up(self):
        lines = self.show(100, self.MANY)
        starts = {line.find("#", 3) for line in lines[: len(lines) - 1]}
        self.assertEqual(len(starts), 1, starts)                 # the second column starts in one place

    def test_the_current_preset_is_marked(self):
        lines = self.show(30, current=8)
        marked = [line for line in lines if style.HERE_MARK in line]
        self.assertEqual(len(marked), 1)
        self.assertIn("Jungle $lash", marked[0])

    def test_no_mark_when_not_known(self):
        self.assertFalse(any(style.HERE_MARK in line for line in self.show(30)))

    def test_a_filter_any_case(self):
        text = "\n".join(self.show(200, arg="CHIME"))
        self.assertIn("Chime 1: Class-A", text)
        self.assertIn("Chime 2: Drive", text)
        self.assertNotIn("Jungle", text)

    def test_nothing_matches(self):
        lines = self.show(80, arg="banjo")
        self.assertEqual(len(lines), 1)
        self.assertIn("no presets match", lines[0])


class TestPreset(unittest.TestCase):
    def test_by_number(self):
        out, service = say("preset 8")
        self.assertEqual(service.selected, 8)
        self.assertIn("Jungle $lash", out)

    def test_by_part_of_a_name_any_case(self):
        out, service = say("preset JUNGLE")
        self.assertEqual(service.selected, 8)
        self.assertIn("Jungle $lash", out)

    def test_several_matches_are_listed_and_none_loaded(self):
        out, service = say("preset chime")
        self.assertFalse(hasattr(service, "selected"))
        self.assertIn("Chime 1: Class-A", out)
        self.assertIn("Chime 2: Drive", out)

    def test_no_match(self):
        out, service = say("preset banjo")
        self.assertFalse(hasattr(service, "selected"))
        self.assertIn("banjo", out)

    def test_a_bad_number_is_an_error(self):
        out, service = say("preset 999")
        self.assertFalse(hasattr(service, "selected"))
        self.assertIn(style.BAD_MARK, out)

    def test_nothing_given_shows_the_usage(self):
        assert_usage(self, "preset", "usage: preset")


class TestPresetKnob(unittest.TestCase):
    KNOB = {0: "Bass", 4: "Chime 1: Class-A", 8: "Jungle $lash", 9: "Chunk 2: Phat Chunk",
            11: "Insane 2: Criminal", 16: "Brit Plexi 45"}

    def lines(self, position=None, presets=KNOB):
        """ preset_knob's output as {marking: (slot, line)}. """
        service = FakeService()
        service.PRESETS = dict(presets)
        service._state.knob_position = position
        out, _ = say("preset_knob", service)
        rows = {}
        for line in out.splitlines():
            words = line.replace(style.HERE_MARK, "").split()        # the current row starts with ▶
            if len(words) >= 2 and words[0].isdigit():
                rows[int(words[0])] = (int(words[1].strip("#")), line)
        return rows

    def test_sixteen_markings_in_order(self):
        self.assertEqual(list(self.lines()), list(range(1, 17)))

    def test_marking_m_is_slot_m_plus_8(self):
        rows = self.lines()
        self.assertEqual(rows[1][0], 9)
        self.assertEqual(rows[3][0], 11)
        self.assertEqual(rows[8][0], 0)
        self.assertEqual(rows[16][0], 8)
        self.assertIn("Insane 2: Criminal", rows[3][1])
        self.assertIn("Jungle $lash", rows[16][1])

    def test_only_slots_0_to_15(self):
        out, _ = say("preset_knob")
        self.assertNotIn("Brit Plexi 45", "".join(line for _, line in self.lines().values()))

    def test_the_knob_is_marked(self):
        rows = self.lines(position=3)
        self.assertTrue(rows[3][1].lstrip().startswith(style.HERE_MARK))
        self.assertEqual([m for m, (_, line) in rows.items() if style.HERE_MARK in line], [3])

    def test_position_0_is_marking_16(self):
        rows = self.lines(position=0)
        self.assertEqual([m for m, (_, line) in rows.items() if style.HERE_MARK in line], [16])

    def test_no_mark_when_not_known(self):
        rows = self.lines(position=None)
        self.assertFalse(any(style.HERE_MARK in line for _, line in rows.values()))

    def test_the_rows_line_up(self):
        # The marked row and the others start their marking in the same column.
        rows = self.lines(position=3)
        starts = {line.index(str(m)) - (0 if m >= 10 else 1) for m, (_, line) in rows.items()}
        self.assertEqual(len(starts), 1, starts)

    def test_a_missing_name_is_a_question_mark(self):
        rows = self.lines(presets={})
        self.assertIn("?", rows[5][1])
        self.assertNotIn("error", rows[5][1])


class TestGet(unittest.TestCase):
    def test_a_known_value(self):
        service = FakeService()
        service.values["bass"] = 0.625
        out, _ = say("get Bass", service)
        self.assertIn("0.62", out)                   # 2 decimals

    def test_not_known_yet(self):
        out, _ = say("get bass")
        self.assertIn("not known", out)

    def test_a_name_with_spaces(self):
        service = FakeService()
        service.values["eq low-mid gain"] = 0.7
        out, _ = say("get eq low-mid gain", service)
        self.assertIn("0.70", out)

    def test_an_unknown_name_is_an_error(self):
        out, _ = say("get banjo")
        self.assertIn(style.BAD_MARK, out)

    def test_no_name_is_a_usage_hint(self):
        assert_usage(self, "get", "usage: get")


class TestSet(unittest.TestCase):
    def test_sets_it(self):
        out, service = say("set bass 0.3")
        self.assertEqual(service.sets, [("bass", 0.3)])
        self.assertIn("0.3", out)

    def test_the_value_is_the_last_word(self):
        out, service = say("set EQ Low-Mid Gain 0.7")
        self.assertEqual(service.sets, [("eq low-mid gain", 0.7)])

    def test_bad_input_is_an_error_and_sends_nothing(self):
        for command in ("set bass loud", "set bass 2", "set banjo 0.5"):
            with self.subTest(command=command):
                out, service = say(command)
                self.assertIn(style.BAD_MARK, out)
                self.assertEqual(service.sets, [])

    def test_missing_parts_are_a_usage_hint(self):
        for command in ("set bass", "set"):
            with self.subTest(command=command):
                assert_usage(self, command, "usage: set")


class TestOnOff(unittest.TestCase):
    def test_on_adds_the_on(self):
        out, service = say("on reverb")
        self.assertEqual(service.sets, [("reverb on", 1)])
        self.assertIn("on", out)

    def test_off_with_the_full_name(self):
        out, service = say("off Delay On")
        self.assertEqual(service.sets, [("delay on", 0)])
        self.assertIn("off", out)

    def test_not_a_switch_is_an_error(self):
        out, service = say("on banjo")
        self.assertIn(style.BAD_MARK, out)
        self.assertEqual(service.sets, [])

    def test_no_name_is_a_usage_hint(self):
        for command in ("off", "on"):
            with self.subTest(command=command):
                assert_usage(self, command, "usage: on")


class TestParams(unittest.TestCase):
    def test_lists_them_all(self):
        out, _ = say("params")
        for p in PARAMETERS:
            if p.record is not None:
                self.assertIn(p.name, out)          # as written, not lower-cased

    def test_not_the_tap_button(self):
        # Tap (Hold) is the button, not the tempo, and no dump holds a value for it.
        out, _ = say("params")
        self.assertNotIn("Tap (Hold)", out)

    def test_the_tempo_is_the_last_row(self):
        service = FakeService()
        service._state.bpm = 116.0
        out, _ = say("params", service)
        last = [line for line in out.splitlines() if line.strip()][-1]
        self.assertIn("Tempo", last)
        self.assertIn("116.0 bpm", last)

    def test_no_tempo_yet(self):
        out, _ = say("params")
        last = [line for line in out.splitlines() if line.strip()][-1]
        self.assertTrue(last.rstrip().endswith("-"), last)

    def test_each_parameter_once(self):
        out, _ = say("params bass")
        self.assertEqual([line for line in out.splitlines() if "Bass" in line].__len__(), 1, out)

    def test_a_meter_for_floats_and_words_for_switches(self):
        service = FakeService()
        service.values.update({"bass": 0.5, "reverb on": 1, "delay on": 0})
        out, _ = say("params", service)
        lines = {line.split("  ")[0].strip(): line for line in out.splitlines() if line.strip()}
        self.assertIn(style.METER_FULL * 5 + style.METER_EMPTY * 5, lines["Bass"])
        self.assertTrue(lines["Reverb On"].rstrip().endswith("on"))
        self.assertTrue(lines["Delay On"].rstrip().endswith("off"))

    def test_a_range_other_than_0_to_1(self):
        # Gate Threshold is 14 to 77: the middle of that is a half-full meter.
        service = FakeService()
        service.values["gate threshold"] = 45.5
        out, _ = say("params gate threshold", service)
        self.assertIn(style.METER_FULL * 5 + style.METER_EMPTY * 5, out)

    def test_values_and_not_known(self):
        service = FakeService()
        service.values["bass"] = 0.5
        out, _ = say("params bass", service)
        self.assertIn("0.50", out)
        self.assertNotIn("0.500000", out)
        out, _ = say("params treble")
        self.assertIn("-", out)
        self.assertNotIn("None", out)

    def test_a_filter_any_case(self):
        out, _ = say("params EQ LOW")
        self.assertIn("EQ Low Gain", out)
        self.assertIn("EQ Low-Mid Gain", out)
        self.assertNotIn("Bass", out)


class TestModels(unittest.TestCase):
    def test_none_yet(self):
        out, _ = say("models")
        self.assertIn("No models yet", out)
        self.assertNotIn("error", out)

    def test_name_then_id_then_number(self):
        service = FakeService()
        service._state.models = {
            "amp": {"number": 220, "id": "ClassA30TopBoost", "name": "1967 Class A-30 Top Boost"},
            "reverb": {"number": 17, "id": "ClassicSpring", "name": None},
            "wah": {"number": 3, "id": None, "name": None},
        }
        out, _ = say("models", service)
        self.assertIn("1967 Class A-30 Top Boost", out)
        self.assertNotIn("ClassA30TopBoost", out)
        self.assertIn("ClassicSpring", out)
        lines = {line.split()[0]: line.split()[-1] for line in out.splitlines() if line.strip()}
        self.assertEqual(lines["wah"], "3")


def loaded():
    """ A FakeService with preset 8 loaded. """
    service = FakeService()
    service.select_preset(8)
    return service


def answering(answer, command, service):
    """ Run a command with `answer` typed at input(); returns what it printed. """
    out = io.StringIO()
    with mock.patch("sys.stdin", io.StringIO(answer + "\n")), mock.patch("sys.stdout", out):
        cli.Shell(service).onecmd(command)
    return out.getvalue()


class TestSave(unittest.TestCase):
    def test_y_saves(self):
        service = loaded()
        out = answering("y", "save", service)
        self.assertIn('Overwrite preset 8 "Jungle $lash"', out)
        self.assertEqual(service.saved, 8)
        self.assertIn("Jungle $lash", out.split("saving")[-1])

    def test_anything_else_doesnt(self):
        for answer in ("n", "", "yes please", "Y "):
            with self.subTest(answer=answer):
                service = loaded()
                out = answering(answer, "save", service)
                if answer.strip().lower() == "y":
                    self.assertEqual(service.saved, 8)      # "Y " counts as y
                else:
                    self.assertFalse(hasattr(service, "saved"))
                    self.assertIn("Not saved", out)

    def test_no_slot_is_an_error_without_asking(self):
        service = FakeService()
        out = answering("y", "save", service)
        self.assertIn(style.BAD_MARK, out)
        self.assertNotIn("Overwrite", out)
        self.assertFalse(hasattr(service, "saved"))


class TestWatch(unittest.TestCase):
    def changes(self, service):
        service.emit(EventType.PARAMETER_CHANGED, key=(0x25, 4, 2), name="Bass", value=0.41)
        service.emit(EventType.PARAMETER_CHANGED, key=(0x25, 9, 2), name=None, value=0.5)
        service.emit(EventType.KNOB_MOVED, position=3)
        service.emit(EventType.TAP, bpm=120.0)

    def test_on_shows_changes(self):
        service = FakeService()
        sh = cli.Shell(service)
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            sh.onecmd("watch on")
            self.changes(service)
        text = out.getvalue()
        self.assertIn("Bass = 0.41", text)
        self.assertIn("(37, 9, 2) = 0.50", text)     # no name: the key
        self.assertIn("3", text)
        self.assertIn("120", text)

    def test_off_by_default_and_after_off(self):
        service = FakeService()
        sh = cli.Shell(service)
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.changes(service)
            sh.onecmd("watch on")
            sh.onecmd("watch off")
            before = out.getvalue()
            self.changes(service)
        self.assertNotIn("Bass", out.getvalue())
        self.assertEqual(out.getvalue(), before)

    def test_anything_else_is_usage(self):
        assert_usage(self, "watch", "usage: watch")


class TestLog(unittest.TestCase):
    def tearDown(self):
        Logger.enabled = True

    def test_off_hides_log_lines_and_on_brings_them_back(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            say("log off")
            Logger("Test").info("hidden")
            say("log on")
            Logger("Test").info("shown")
        self.assertNotIn("hidden", out.getvalue())
        self.assertIn("shown", out.getvalue())

    def test_anything_else_is_usage(self):
        assert_usage(self, "log maybe", "usage: log")
        self.assertTrue(Logger.enabled)


class TestDidYouMean(unittest.TestCase):
    def test_a_typo_gets_a_suggestion(self):
        out, _ = say("staus")
        self.assertIn("did you mean", out)
        self.assertIn("status", out)

    def test_nothing_close_points_at_help(self):
        out, _ = say("frobnicate")
        self.assertIn("help", out)
        self.assertNotIn("did you mean", out)

    def test_eof_is_never_suggested(self):
        out, _ = say("EOFF")
        self.assertNotIn("EOF", out.replace("EOFF", ""))


class TestCompletion(unittest.TestCase):
    def complete(self, method, line):
        """ What Tab offers at the end of `line`, the way readline calls it (last word only). """
        begidx = max(line.rfind(" "), line.rfind("-")) + 1    # readline's default word breaks
        text = line[begidx:]
        return getattr(shell(), method)(text, line, begidx, len(line))

    def test_after_the_first_word(self):
        self.assertIn("Low Gain", self.complete("complete_get", "get eq lo"))

    def test_after_a_dash(self):
        self.assertIn("Mid Gain", self.complete("complete_get", "get eq low-mi"))

    def test_any_case_and_only_matches(self):
        offered = self.complete("complete_params", "params BA")
        self.assertEqual(offered, ["Bass"])

    def test_set_too(self):
        self.assertIn("Treble", self.complete("complete_set", "set tre"))

    def test_preset_names(self):
        self.assertEqual(self.complete("complete_preset", "preset jun"), ["Jungle $lash"])

    def test_nothing_typed_offers_everything(self):
        self.assertEqual(len(self.complete("complete_get", "get ")), len(PARAMETERS))


class TestHelp(unittest.TestCase):
    def test_eof_is_hidden(self):
        sh = shell()
        sh.onecmd("help")
        self.assertNotIn("EOF", sh.stdout.getvalue())

    def test_help_lists_the_commands(self):
        sh = shell()
        sh.onecmd("help")
        text = sh.stdout.getvalue()
        for command in ("exit", "quit", "status", "preset", "presets", "preset_knob",
                        "get", "set", "on", "off", "params", "models",
                        "save", "watch", "log"):
            self.assertIn(command, text)

    def test_help_for_one_command(self):
        sh = shell()
        sh.onecmd("help exit")
        self.assertIn("Disconnect from the amp", sh.stdout.getvalue())

    def test_every_command_has_help(self):
        # A command without a docstring shows up under "Undocumented commands".
        for name in dir(cli.Shell):
            if name.startswith("do_") and name != "do_EOF":
                with self.subTest(command=name[3:]):
                    self.assertTrue(getattr(cli.Shell, name).__doc__)


class TestStart(unittest.TestCase):
    def test_log_lines_are_hidden_once_connected(self):
        out, _, enabled = run(["exit"])
        self.assertFalse(enabled)
        self.assertIn("log on", out)

    def test_banner_connect_and_prompt(self):
        out, service, _ = run(["exit"])
        self.assertIn(silkline.__version__, out)
        self.assertIn("connecting", out)
        self.assertIn("connected", out)
        self.assertIn("silkline> ", out)

    def test_the_loaded_preset_is_shown(self):
        out, service, _ = run(["exit"])
        self.assertIn("Chime 1: Class-A", out)

    def test_it_disconnects_at_the_end(self):
        out, service, _ = run(["exit"])
        self.assertTrue(service.stopped)

    def test_end_of_input_leaves_too(self):
        out, service, _ = run([])                       # Ctrl-D straight away
        self.assertTrue(service.stopped)

    def test_no_prompt_until_connected(self):
        # An amp that never connects: the prompt never comes. Ctrl-C (KeyboardInterrupt
        # while waiting) leaves cleanly and still disconnects.
        service = FakeService(connects=False)
        with mock.patch.object(threading.Event, "wait", side_effect=KeyboardInterrupt):
            out, service, _ = run(["exit"], service)
        self.assertNotIn("silkline> ", out)
        self.assertIn("Could not find amp port", out)
        self.assertTrue(service.stopped)


if __name__ == "__main__":
    unittest.main()
