"""
models.py

Model names from the Line 6 app's .models files (protocol.md section 10).

The files are the app's own (its res folder, copied to app_data/ and never
committed). The symbol table (symbols.py) turns the amp's model number into a
model ID like "DoubleVerb"; these files turn the ID into "1965 Double Verb".
"""
import json
from pathlib import Path

from spiderweb.protocol.dump import stage_models
from spiderweb.protocol.symbols import load_symbols

_CAB_MICS = ("57OnAxis", "57OffAxis", "421", "U67")      # a cab's model ID ends with its mic

def _load_model_names(folder):
    """Every model in the folder's .models files, as {model ID: name}.

    The full name ("1965 Double Verb"), not the short one. No model is in two
    files. A folder with no .models files (or no folder) gives {}.
    """
    names = {}
    for path in sorted(Path(folder).glob("*.models")):
        for model in json.loads(path.read_text(encoding="utf-8")):
            names[model["symbolicID"]] = model["name"]
    return names

def _model_name(symbol, names):
    """The name for a model ID, or None if names has none.

    A cab's ID ends with its mic ("2x12ClassAStudio57OnAxis"), but the files name
    the cab without it, so the mic is cut off when that gives a known cab.
    """
    if symbol in names:
        return names[symbol]
    for mic in _CAB_MICS:            # a cab: cut the mic off and try again
        if symbol.endswith(mic) and symbol[:-len(mic)] in names:
            return names[symbol[:-len(mic)]]
    return None


class ModelNames:
    """The Line 6 app's files, loaded once, to name the models in a dump.

    ModelNames(folder) loads the symbol table and the .models files from folder (the
    app's res folder, app_data/); it raises FileNotFoundError if the table isn't
    there. ModelNames(None) loads nothing, so describe() gives numbers only.
    """

    def __init__(self, folder):
        self.symbols = []
        self.names = {}

        if folder is None:
            return

        self.symbols = load_symbols(Path(folder) / "defaultSymbolTable_Parker.bin")
        self.names = _load_model_names(Path(folder))

    def describe(self, dump):
        """Each stage's model in a dump: {stage: {"number", "id", "name"}}.

        number is what the amp sends; id the symbol table's name for it and name
        the .models files' name, each None without the Line 6 files (or for a
        model they don't know).
        """
        models = {}
        for stage, number in stage_models(dump).items():
            symbol = name = None
            if (number < len(self.symbols)):
                symbol = self.symbols[number]
                name = _model_name(symbol, self.names)
            models[stage] = {"number": number, "id": symbol, "name": name} 
        return models