# Silkline

A Python library for controlling a **Line 6 Spider V MkII** amp over USB: read and set
every knob and switch, load and save presets, see each stage's model, and follow what
happens on the amp itself (knob turns, the preset knob, the tap button), with automatic
reconnecting when the amp is unplugged or switched off.

It talks to the amp the way Line 6's own Spider V Remote app does, worked out from USB
captures (see [docs/protocol.md](docs/protocol.md)). It was built and tested on a
Raspberry Pi with a Spider V 20 MkII.

> Not affiliated with or endorsed by Line 6. "Line 6" and "Spider V" are Line 6's
> trademarks, used here only to say which amp this works with.

## What it needs

- **Linux** (a Raspberry Pi works well), with **Python 3.10 or newer**. Nothing else to
  install: Silkline only uses Python's own modules.
- The amp connected by **USB** and switched on.
- Permission to use the amp's MIDI device (`/dev/snd/midiC*D0`). On most systems that
  means being in the `audio` group: `sudo usermod -aG audio $USER`, then log in again.

## Install

From a copy of this repo:

```bash
pip install -e ~/silkline
```

`-e` (editable) means a project using Silkline uses this folder directly, so changes
here are picked up without reinstalling. Leave it out for a normal install. Straight
from GitHub, at a fixed version:

```bash
pip install "git+https://github.com/JWobz/silkline.git@v1.0"
```

### Model names (optional)

The amp only says which model each stage uses as a number. To show names like "1965
Double Verb", Silkline reads the **free Spider V Remote app's own files**. They're Line
6's, so they aren't part of this repo: copy the app's `res` folder to
`~/.config/silkline/app_data`. From a Windows PC with the app installed:

```bash
scp -r "/c/Program Files (x86)/Line6/Spider V Remote/res" pi@raspberrypi:~/.config/silkline/app_data
```

Without them everything still works; models just have numbers instead of names.

## A first example

```python
from silkline import AmpService, EventType

amp = AmpService()

def on_change(event):
    # Runs on Silkline's reader thread: keep it quick, and don't call commands from it.
    if event.event_type == EventType.PARAMETER_CHANGED:
        print(f"{event.data['name']} -> {event.data['value']:.2f}")
    elif event.event_type == EventType.PRESET_CHANGED:
        print("preset:", event.data["name"])

amp.on_change(on_change)
amp.start()                                  # connect and read the amp (about 15 s)

state = amp.state()
print(state.preset_name, "-", state.models["amp"]["name"])

amp.set("gain", 0.8)                         # any parameter by name, any case
amp.set("reverb on", 1)                      # on/off switches take 0 or 1
amp.select_preset(4)                         # load a preset (nothing is saved)
print(amp.get("volume"))

amp.stop()
```

For a long-running program (a server, say), use `amp.keep_connected()` instead of
`start()`: it connects in the background and reconnects by itself after an unplug or a
power-cycle. For sliders, use `amp.set_latest(name, value)`, which keeps up with fast
moves without flooding the amp.

## What you can control

- **Amp:** Gain or Drive (whichever the amp model has), Bass, Mid, Treble, Presence
- **Panel:** Volume, Reverb, the Stomp, Mod and Delay knobs
- **Every stage on or off:** gate, wah, stomp, mod, comp, EQ, volume pedal, delay, reverb
- **Noise gate, volume pedal, compressor, the 4-band EQ, reverb** controls
- **Presets:** the list of names, loading one, and saving the current one into its slot
- **Each stage's model**, read from every preset

The full list of names and ranges, the events, the state and the threading rules are
in [docs/api.md](docs/api.md).

## Not yet (planned for 1.1)

Changing a stage's model, moving stages in the chain, saving to a different slot, the
chain order, the knobs that depend on a stage's model, and exporting and importing
tones (including the app's own tone files).

## Working on Silkline

```bash
python3 -m unittest          # the tests: no amp needed, they use real captures
```

- [docs/protocol.md](docs/protocol.md): everything known about the amp's USB messages,
  and how it was found.
- [docs/windows_capture.md](docs/windows_capture.md): recording the app with Wireshark,
  to work out more.
- `tools/`: the scripts used to work out the protocol and check it on a real amp
  (`finish_check`, `dump_params`, `send`, `console`, `watch`, `pcap_to_text`).
- `captures/`: the recordings the tests and the protocol notes rely on.
