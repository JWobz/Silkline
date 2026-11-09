"""Model names from the Line 6 app's .models files (silkline/protocol/models.py,
protocol.md section 10).

- Made-up .models files, written here, check the rules on any machine.
- The real files in app_data/ (the app's own, never in git) check the names of models
  seen in the captures; those tests skip themselves when app_data/ isn't there.
"""
import json
import tempfile
import unittest
from pathlib import Path

from silkline.protocol.models import _CAB_MICS, _load_model_names, _model_name

ROOT = Path(__file__).resolve().parent.parent
APP_DATA = ROOT / "app_data"      # the Line 6 app's res folder, copied here (never in git)


class MadeUpFolder(unittest.TestCase):
    def folder(self, files):
        """ A temporary folder with {file name: list of models} written as JSON. """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, models in files.items():
            (Path(tmp.name) / name).write_text(json.dumps(models), encoding="utf-8")
        return tmp.name


def model(symbol, name, **more):
    return {"symbolicID": symbol, "name": name, "shortname": name, "params": [], **more}


class TestLoadModelNames(MadeUpFolder):
    def test_every_file_is_read(self):
        folder = self.folder({
            "amps.models": [model("DoubleVerb", "1965 Double Verb"), model("JazzClean", "1987 Jazz Clean")],
            "stomps.models": [model("FuzzPi", "Fuzz Pi")],
        })
        self.assertEqual(_load_model_names(folder), {
            "DoubleVerb": "1965 Double Verb", "JazzClean": "1987 Jazz Clean", "FuzzPi": "Fuzz Pi"})

    def test_the_full_name_not_the_short_one(self):
        folder = self.folder({"amps.models": [model("DoubleVerb", "1965 Double Verb", shortname="Double Verb")]})
        self.assertEqual(_load_model_names(folder)["DoubleVerb"], "1965 Double Verb")

    def test_only_models_files(self):
        folder = self.folder({"amps.models": [model("A", "a")], "default_preset.json": [model("B", "b")]})
        self.assertEqual(_load_model_names(folder), {"A": "a"})

    def test_names_with_quotes_and_accents(self):
        folder = self.folder({"cabs.models": [model("4x12Green25sStudio", "4x12 Green 25's"),
                                              model("Cafe", "Café")]})
        names = _load_model_names(folder)
        self.assertEqual((names["4x12Green25sStudio"], names["Cafe"]), ("4x12 Green 25's", "Café"))

    def test_takes_a_path_too(self):
        folder = self.folder({"amps.models": [model("A", "a")]})
        self.assertEqual(_load_model_names(Path(folder)), {"A": "a"})

    def test_an_empty_folder(self):
        self.assertEqual(_load_model_names(self.folder({})), {})


class TestModelName(unittest.TestCase):
    NAMES = {"DoubleVerb": "1965 Double Verb", "2x12ClassAStudio": "2x12 Class A",
             "4x12TreadplateStudio": "4x12 Treadplate"}

    def test_a_model(self):
        self.assertEqual(_model_name("DoubleVerb", self.NAMES), "1965 Double Verb")

    def test_a_cab_with_each_mic(self):
        for mic in _CAB_MICS:
            with self.subTest(mic=mic):
                self.assertEqual(_model_name("2x12ClassAStudio" + mic, self.NAMES), "2x12 Class A")

    def test_an_unknown_model_is_none(self):
        self.assertIsNone(_model_name("SpiderVGuitarFlow", self.NAMES))

    def test_a_mic_ending_is_only_cut_when_the_rest_is_a_cab(self):
        self.assertIsNone(_model_name("Something421", self.NAMES))

    def test_an_unknown_cab_is_none(self):
        self.assertIsNone(_model_name("9x9NowhereStudio57OnAxis", self.NAMES))

    def test_an_empty_table(self):
        self.assertIsNone(_model_name("DoubleVerb", {}))


@unittest.skipUnless((APP_DATA / "amps.models").exists(), "app_data/ isn't here (the Line 6 app's files are never in git)")
class TestTheRealFiles(unittest.TestCase):
    """ The app's files, against the models in the captures (2026-11-08 survey). """

    @classmethod
    def setUpClass(cls):
        cls.names = _load_model_names(APP_DATA)

    def test_261_models(self):
        # 11 files, no model in two of them
        self.assertEqual(len(self.names), 261)

    def test_the_amps_in_the_users_notes(self):
        # models.pcapng, named by the user from the app (protocol.md section 3)
        for symbol, name in (("DoubleVerb", "1965 Double Verb"), ("JazzClean", "1987 Jazz Clean"),
                             ("ClassA30TopBoost", "1967 Class A-30 Top Boost"), ("ClassA15", "1960 Class A-15"),
                             ("BritPlexiVariac", "1968 Plexi Variac'd"), ("Line6ChemicalX", "Line 6 Chemical X")):
            with self.subTest(symbol=symbol):
                self.assertEqual(self.names[symbol], name)

    def test_effects_and_fixed_blocks(self):
        for symbol, name in (("FuzzPi", "Fuzz Pi"), ("Gate", "Noise Gate"), ("SharcPodFixedComp", "Compressor")):
            with self.subTest(symbol=symbol):
                self.assertEqual(self.names[symbol], name)

    def test_cabs_from_the_dumps(self):
        for symbol, name in (("4x12Green25sStudio57OnAxis", "4x12 Green 25's"),
                             ("2x12ClassAStudio57OnAxis", "2x12 Class A"),
                             ("4x12BritT75StudioU67", "4x12 Brit T75"),
                             ("4x12TreadplateStudio421", "4x12 Treadplate")):
            with self.subTest(symbol=symbol):
                self.assertEqual(_model_name(symbol, self.names), name)

    def test_the_panel_and_air_have_no_name(self):
        self.assertIsNone(_model_name("SpiderVGuitarFlow", self.names))
        self.assertIsNone(_model_name("TNGAIRReflections", self.names))


if __name__ == "__main__":
    unittest.main()
