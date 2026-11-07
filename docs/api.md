# SpiderWeb-Amp API

`AmpService` (`spiderweb/service.py`) is the one owner of the amp. The server (phase 8)
and the tools talk to it only. Everything below `AmpService` (`Amp`, `Connection`,
`AmpTransport`, `spiderweb/protocol/`) is internal. The wire format is in
`docs/protocol.md`.

Updated 2026-11-07, after phase 6, reading values from dumps, the drive pick and
`set_latest`, and leaving out preset 115. 350 tests (`python3 -m unittest`).

## Starting and stopping

| Call | What it does |
|---|---|
| `AmpService(amp_factory=default_amp, reconnect_delays=(1, 2, 5, 10, 30))` | Makes the service. Touches nothing until started. |
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
| `save()` | name | **Overwrites the loaded preset on the amp** with how it is now (every set included): takes a fresh dump, uploads it to the slot `select_preset()` loaded, reads it back and sends `PRESET_SAVED`. Can't be undone. `ValueError` if the slot isn't known (after the handshake or a preset-knob move: call `select_preset()` first). Not yet tried on the amp: try it on a preset you don't mind losing. |
| `presets()` | `{index: name}` | The 127 loadable presets' names, read from the handshake (115 is left out). A copy. |
| `state()` | `AmpState` | A copy of everything below. |
| `on_change(callback)` | – | `callback(event)` for every `Event`. Keep it quick. |

Errors (`spiderweb/errors.py`): `AmpError` is the base; `AmpDisconnected` (a command while
not connected), `AmpTimeout` (no answer), `AmpNotFound` (no amp on USB). `ValueError` for
an unknown or unsettable parameter, or a value out of range.

## State (`spiderweb/state.py`)

`AmpState`, `None` meaning "not known yet":

| Field | Meaning |
|---|---|
| `connection` | `ConnectionState.DISCONNECTED`, `CONNECTING` or `CONNECTED` |
| `preset_number` | the last `select_preset()` value; `None` after a knob move or a reconnect (which knob position loads which preset is in protocol.md section 11) |
| `preset_name` | from the handshake dump, `select_preset()`, or the refresh after a knob move |
| `knob_position` | 0 to 15, once the preset knob has settled (the knob's marking 16 is 0) |
| `params` | `{(block, id, namespace): value}`: read from each dump (`read_values`, protocol.md section 3), then updated by sets and knob reports. Replaced on every select, knob click and reconnect. On/off switches are 0 or 1 |
| `bpm` | from the tap button |

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
  to the waiting command, and everything else to `handle_message`, which updates the
  state and sends events. `on_change` callbacks run here.
- **Supervisor** (`amp-supervisor`, while `keep_connected()` runs): connects and reconnects.
- **Commands** run on the caller's thread and wait for the reader.

## Parameters (`spiderweb/protocol/parameters.py`)

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

## Gain and Drive

Each amp model has one of the two: Gain (0x25) or Drive (0x26). They're the same knob,
so **`"gain"` and `"drive"` both act on whichever one the current preset has** (the dump
says which), and work on every preset. `PARAMETER_CHANGED` events name the real one, so
treat both as the same control. Before any dump, the one asked for is sent.

## Rules the service follows (protocol.md)

- Knob reports count only when they move by 0.02 or more; 2A/02 is ignored.
- The preset-knob position is settled at the status message that follows a click (contact
  bounce, section 11), and then the new preset's name is read from a dump.
- The amp never reports a set back, so a set's value is what was sent.

## Not done yet

- Checking reconnects on the real amp (pull the USB, power-cycle) with `keep_connected()`.
- The server and the phone page (phase 8).
