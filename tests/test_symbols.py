"""Reading the Line 6 app's symbol table (spiderweb/protocol/symbols.py, protocol.md section 10).

Two kinds of test:
- Made-up tables, built here, so the reader's rules are checked on any machine.
- The real table, app_data/defaultSymbolTable_Parker.bin. It's the app's own file and
  isn't in git, so those tests skip themselves when the app_data/ folder isn't there.
"""
import struct
import tempfile
import unittest
from pathlib import Path

from spiderweb.protocol.symbols import load_symbols

ROOT = Path(__file__).resolve().parent.parent
APP_DATA = ROOT / "app_data"      # the Line 6 app's res folder, copied here (never in git)
PARKER = APP_DATA / "defaultSymbolTable_Parker.bin"


def make_table(names):
    """ A symbol table in the app's layout: count, size, then (offset, hash, length) for
    each name, then the names, each followed by a 00. The hash is left as 0. """
    area, entries = bytearray(), bytearray()
    for name in names:
        raw = name.encode("latin-1")
        entries += struct.pack("<III", len(area), 0, len(raw))
        area += raw + b"\x00"
    body = entries + area
    return struct.pack("<II", len(names), 8 + len(body)) + body


class TempTable(unittest.TestCase):
    def write(self, data):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "table.bin"
        path.write_bytes(data)
        return path


class TestMadeUpTables(TempTable):
    def test_names_in_order(self):
        path = self.write(make_table(["TNGAIRReflections", "LevelState", "Gain"]))
        self.assertEqual(load_symbols(path), ["TNGAIRReflections", "LevelState", "Gain"])

    def test_the_position_is_the_number(self):
        names = [f"name{i}" for i in range(300)]
        self.assertEqual(load_symbols(self.write(make_table(names)))[0xCA], "name202")

    def test_takes_a_string_path_too(self):
        path = self.write(make_table(["Gain"]))
        self.assertEqual(load_symbols(str(path)), ["Gain"])

    def test_names_can_be_numbers_and_odd_bytes(self):
        # The real table has names like "0.54" and "2x12Line6"; latin-1 never fails.
        names = ["0.54", "2x12Line6", "Caf\xe9"]
        self.assertEqual(load_symbols(self.write(make_table(names))), names)

    def test_an_empty_table(self):
        self.assertEqual(load_symbols(self.write(make_table([]))), [])

    def test_a_wrong_size_is_refused(self):
        data = make_table(["Gain"]) + b"extra"
        with self.assertRaises(ValueError):
            load_symbols(self.write(data))

    def test_another_file_is_refused(self):
        with self.assertRaises(ValueError):
            load_symbols(self.write(b'[{"symbolicID": "Gain"}]'))     # a .models file, say

    def test_a_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_symbols(Path(tempfile.gettempdir()) / "no such table.bin")


@unittest.skipUnless(PARKER.exists(), "app_data/ isn't here (the Line 6 app's files are never in git)")
class TestTheRealTable(unittest.TestCase):
    """ The Spider V MkII's table (protocol.md section 3, "Names: the amp's symbol table"). """

    @classmethod
    def setUpClass(cls):
        cls.names = load_symbols(PARKER)

    def test_910_names(self):
        self.assertEqual(len(self.names), 910)

    def test_amp_models(self):
        # Kinds seen in the dumps (2A:0), checked against the user's notes of each model.
        for kind, name in ((0xCA, "DoubleVerb"), (0xDC, "ClassA30TopBoost"), (0xC1, "JazzClean"),
                           (0x9C, "Line6Lunatic"), (0xB0, "Line6ChemicalX")):
            with self.subTest(kind=hex(kind)):
                self.assertEqual(self.names[kind], name)

    def test_the_fixed_blocks(self):
        self.assertEqual(self.names[0x316], "SpiderVGuitarFlow")      # the panel, 74:3
        self.assertEqual(self.names[0x25E], "Gate")                   # 5E:2
        self.assertEqual(self.names[0x261], "SharcPodFixedComp")      # 23:3
        self.assertEqual(self.names[0x269], "ParaGraphic4_band")      # 25:3

    def test_amp_knob_ids_and_their_state_records(self):
        # Wire ids in namespace 0 are symbols; the dump stores them as "...State".
        for wire, record, name in ((0x25, 0x1F, "Gain"), (0x26, 0x33, "Drive"), (0x21, 0x1C, "Bass")):
            with self.subTest(name=name):
                self.assertEqual(self.names[wire], name)
                self.assertEqual(self.names[record], name + "State")

    def test_the_first_name(self):
        self.assertEqual(self.names[0], "TNGAIRReflections")


class TestLine6FilesStayOutOfGit(unittest.TestCase):
    """ protocol.md section 10: the app's files and login.json must never be committed. """

    def ignored(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        return {line.strip() for line in lines}

    def test_the_app_data_folder_is_ignored(self):
        self.assertTrue({"app_data/", "app_data", "/app_data/", "/app_data"} & self.ignored(),
                        "add app_data/ to .gitignore, on its own line")

    def test_login_json_is_ignored(self):
        self.assertIn("login.json", self.ignored())


if __name__ == "__main__":
    unittest.main()
