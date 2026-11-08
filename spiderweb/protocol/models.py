"""Model names from the Line 6 app's .models files (protocol.md section 10).

The files are the app's own (its res folder, copied to app_data/ and never
committed). The symbol table (symbols.py) turns the amp's model number into a
model ID like "DoubleVerb"; these files turn the ID into "1965 Double Verb".
"""
import json
from pathlib import Path

CAB_MICS = ("57OnAxis", "57OffAxis", "421", "U67")      # a cab's model ID ends with its mic

def load_model_names(folder):
    """Every model in the folder's .models files, as {model ID: name}.

    The full name ("1965 Double Verb"), not the short one. No model is in two
    files. A folder with no .models files (or no folder) gives {}.
    """
    names = {}
    for path in sorted(Path(folder).glob("*.models")):
        for model in json.loads(path.read_text(encoding="utf-8")):
            names[model["symbolicID"]] = model["name"]
    return names

def model_name(symbol, names):
    """The name for a model ID, or None if names has none.

    A cab's ID ends with its mic ("2x12ClassAStudio57OnAxis"), but the files name
    the cab without it, so the mic is cut off when that gives a known cab.
    """
    if symbol in names:
        return names[symbol]
    for mic in CAB_MICS:            # a cab: cut the mic off and try again
        if symbol.endswith(mic) and symbol[:-len(mic)] in names:
            return names[symbol[:-len(mic)]]
    return None