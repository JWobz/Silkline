# Silkline API

`AmpService` (`silkline/service.py`) is the one owner of the amp. Programs and the tools
talk to it only. Everything below `AmpService` (`Amp`, `Connection`, `AmpTransport`,
`silkline/protocol/`) is internal. The wire format is in `docs/protocol.md`.

What a program imports, all from the package itself (`silkline/__init__.py`):
`from silkline import AmpService, AmpState, ConnectionState, Event, EventType,
APP_DATA_FOLDER, AmpError, AmpDisconnected, AmpTimeout, AmpNotFound`.
`silkline.__version__` is the version (`"1.0.0"`). Installing is in the README.

Version 1.0.0 (2026-11-09): every knob and switch by name, presets and `save()`, each
stage's model, reconnecting, and the `silkline` command (`silkline/cli.py`, README). 551 tests (`python3 -m unittest`).

## Starting and stopping

| Call | What it does |
|---|---|
| `AmpService(amp_factory=default_amp, reconnect_delays=(1, 2, 5, 10, 30), resource_folder=APP_DATA_FOLDER)` | Makes the service. Touches nothing on the amp until started. Reads the Line 6 app's files from `resource_folder` (see Model names below); without them models have numbers only. |
| `keep_connected()` | **What the server uses.** Returns at once; an `amp-supervisor` thread connects, and reconnects after any loss: unplug, power-cycle, or a set the amp didn't answer. Waits `reconnect_delays` between failed tries (the last repeats). |
| `start()` | One connect and handshake (about 15 s). Raises `AmpNotFound` (no amp), `AmpError` (the amp isn't ready: no preset list straight after power-on), or `OSError`. For tools and tests. |
| `stop()` | Ends `keep_connected()`, closes the amp, ends `DISCONNECTED`. Safe any time. |

## Commands

All of them wait for the amp, so **never call them from an `on_change` callback** (it
runs on the reader thread).

| Call | Returns | Notes |
|---|---|---|
| `set(name, value)` | – | `name` from Parameters below, any case; `value` in the parameter's range (0 to 1 for most), or 0 / 1 for an on/off. Waits for the amp's answer (about 0 s), then records the value and sends `PARAMETER_CHANGED`. One set at a time: a second waits for the first (the amp ignores all sets after one sent too soon, protocol.md section 8). `AmpTimeout` if unanswered, and then it reconnects. |
| `set_latest(name, value)` | – | **What phone sliders use.** Like `set()`, but if a set is already being sent it returns at once and the value waits; a newer value for the same parameter replaces it. So a drag becomes a few sets: the first, then the newest each time the amp answers. `ValueError` and `AmpDisconnected` are raised at once; errors while sending are only logged (a timeout also reconnects). |
| `get(name)` | float or `None` | The value from the latest dump (the handshake, a select or a knob click), or a later set or knob report. `"gain"` and `"drive"` read whichever of the two the preset uses (see Gain and Drive below). `None` for a parameter with no value yet. |
| `select_preset(n)` | name | `n` = an index in `presets()`. Waits for the dump (up to 4 s). Nothing is saved on the amp. `ValueError` at once for 115 (the amp won't load it) or anything outside 0 to 127. |
| `save()` | name | **Overwrites the loaded preset on the amp** with how it is now (every set included): takes a fresh dump, uploads it to the slot `select_preset()` loaded, reads it back and sends `PRESET_SAVED`. Can't be undone. `ValueError` if the slot isn't known (a preset whose slot can't be told, at connect or after a knob move: call `select_preset()` first). Checked on the amp (2026-11-11). |
| `presets()` | `{index: name}` | The 127 loadable presets' names, read from the handshake (115 is left out). A copy. |
| `state()` | `AmpState` | A copy of everything below. |
| `on_change(callback)` | – | `callback(event)` for every `Event`. Keep it quick. |

Errors (`silkline/errors.py`): `AmpError` is the base; `AmpDisconnected` (a command while
not connected), `AmpTimeout` (no answer), `AmpNotFound` (no amp on USB). `ValueError` for
an unknown or unsettable parameter, or a value out of range.

## State (`silkline/state.py`)

`AmpState`, `None` meaning "not known yet":

| Field | Meaning |
|---|---|
| `connection` | `ConnectionState.DISCONNECTED`, `CONNECTING` or `CONNECTED` |
| `preset_number` | the slot loaded: from `select_preset()`, or after a knob click the knob slot (0 to 15) with the loaded preset's name. At connect, the same from the handshake's preset, but the number only if no other of the 128 presets has its name (the amp may have any preset loaded). `None` when it can't be told: a name not in slots 0 to 15, or a duplicate the click doesn't settle (protocol.md section 11) |
| `preset_name` | from the handshake dump, `select_preset()`, or the refresh after a knob move |
| `knob_position` | 0 to 15 at connect and after a click (the knob's marking 16 is 0): slot − 8 from the loaded preset, or the bounce rule's guess when the slot can't be told |
| `params` | `{(block, id, namespace): value}`: read from each dump (`read_values`, protocol.md section 3), then updated by sets and knob reports. Replaced on every select, knob click and reconnect. On/off switches are 0 or 1 |
| `models` | `{stage: {"number": n, "id": str or None, "name": str or None}}` for the 11 stages (`"gate"`, `"vol"`, `"wah"`, `"stomp"`, `"mod"`, `"delay"`, `"reverb"`, `"amp"`, `"cab"`, `"comp"`, `"eq"`), from every dump, like `params`. See Model names below |
| `bpm` | the preset's saved tempo from every dump (header record 3, protocol.md section 3), then the tap button |

## Events

`Event(event_type, data)`, sent to every `on_change()` callback:

| `EventType` | `data` |
|---|---|
| `CONNECTION_CHANGED` | `{"state": ConnectionState}`, plus `"error"` when the amp was lost or a set went unanswered |
| `PRESET_CHANGED` | `{"number": n or None, "name": str}` |
| `PARAMETER_CHANGED` | `{"key": (block, id, namespace), "name": str or None, "value": float, or 0 / 1 for a switch}` |
| `KNOB_MOVED` | `{"position": 0 to 15}` |
| `TAP` | `{"bpm": float}` |
| `SAVE_PRESSED` | `{}` (the amp's own save button) |
| `PRESET_SAVED` | `{"number": slot, "name": str}`, after `save()` |

A reconnect looks like: `DISCONNECTED` (with `"error"`), `CONNECTING`, then `CONNECTED`, or
`DISCONNECTED` again if that try failed.

## Threads

- **Reader** (`amp-reader`, one per connection): reads everything, hands request replies
  to the waiting command, and everything else to `_handle_message`, which updates the
  state and sends events. `on_change` callbacks run here.
- **Supervisor** (`amp-supervisor`, while `keep_connected()` runs): connects and reconnects.
- **Commands** run on the caller's thread and wait for the reader.

## Parameters (`silkline/protocol/parameters.py`)

Names are any case. Floats are 0 to 1 unless a range is given.

| Stage | Names |
|---|---|
| Amp | Gain, Drive (see below), Bass, Mid, Treble, Presence |
| Panel | Volume, Reverb, Stomp Knob, Mod Knob, Delay Knob |
| On/off (0 or 1) | Gate On, Wah On, Stomp On, Mod On, Comp On, EQ On, Vol On, Delay On, Reverb On |
| Noise gate | Gate Threshold (14 to 77), Gate Decay |
| Volume pedal | Vol Min, Vol Max |
| Compressor | Comp Threshold, Comp Gain |
| EQ | EQ Low / Low-Mid / High-Mid / High, each Freq and Gain (e.g. "EQ Low-Mid Gain") |
| Reverb | Reverb Time, Reverb Tone, Reverb Mix (as seen on a spring model; other models may differ) |

Not yet: knobs that change with a stage's model (wah, stomp, mod, delay), changing a
stage's model, moving stages, and saving to another slot (v1.1, protocol.md section 8).

## Model names

Each stage's model comes from every dump as a number (the amp block's 0xDC, say). The
Line 6 Spider V Remote app's own files turn it into a name: `"id"` from its symbol
table (`ClassA30TopBoost`) and `"name"` from its `.models` files ("1967 Class A-30 Top
Boost"; a cab's name leaves out its mic).

**Those files are Line 6's, so they are never in git.** To get names, install the free
Spider V Remote app and copy its `res` folder to `APP_DATA_FOLDER`,
`~/.config/silkline/app_data` (or pass another folder as `resource_folder`):
```
scp -r "/c/Program Files (x86)/Line6/Spider V Remote/res" you@your-linux-pc:~/.config/silkline/app_data
```
(`.gitignore` still lists `app_data/`, in case the files are ever copied into the project.)
Without the folder the service still works: a warning is logged and `"id"` and `"name"`
are `None`. Stages people can't pick (the panel, 74:3, and 21:3) are left out.


## Gain and Drive

Each amp model has one of the two: Gain (0x25) or Drive (0x26). They're the same knob,
so **`"gain"` and `"drive"` both act on whichever one the current preset has** (the dump
says which), and work on every preset. `PARAMETER_CHANGED` events name the real one, so
treat both as the same control. Before any dump, the one asked for is sent.

## Rules the service follows (protocol.md)

- Knob reports count only when they move by 0.02 or more; 2A/02 is ignored.
- The preset knob is slots 0 to 15 (marking m loads slot (m + 8) % 16). After a click the
  loaded preset is read from a dump, and its name says the slot and the position;
  the bounce rule (section 11) is only a fallback. `KNOB_MOVED` comes just before
  `PRESET_CHANGED`.
- The amp never reports a set back, so a set's value is what was sent.

## Not done yet

Checked on the real amp (2026-11-09, `tools/finish_check.py`): connecting, slider bursts, and
`keep_connected()` reconnecting by itself after a USB replug (18 s) and a power-cycle (25 s),
with sets working again afterwards. The first real `save()` (User 1) kept its change after a
reload.

- Changing a stage's model, moving stages, save-as, the chain order, tone export / import
  (v1.1, protocol.md section 8).
- The server and the phone page (phase 8).
