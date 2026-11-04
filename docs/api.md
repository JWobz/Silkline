AmpService (service.py): the one owner of the amp connection

Methods
  start() / stop()          connect + handshake + start reader thread / stop thread + close
  state() -> AmpState       copy of the current state
  presets() -> dict         preset number -> name (from the handshake)
  select_preset(n) -> str   select, dump, update state; returns the name
  get(name) -> float        last value seen for a parameter
  set(name, value)          set a parameter (Parameter registry, settable only)
  on_change(callback)       callback(Event) on every state change or event

AmpState: connection ("connected" | "reconnecting" | "disconnected"),
          preset_number, preset_name, knob_position, params {key: value}, bpm
Event:    kind + data. Kinds: preset_changed, param_changed, knob_moved, tap,
          save_pressed, connection_changed

Threading
  One background reader thread does all the reading. Sends go through a lock.
  Commands that need a reply wait for the reader to hand it over (queue / event).

Rules
  Params only update on a change >= 0.02. Knob position only after the bounce settles.
  Ignore status, (29, 11, 1) and 2A/02.

Errors
  AmpError (base), AmpDisconnected (command while not connected), AmpTimeout (no reply)
  Connection error, or 2 command timeouts in a row -> reconnect:
    3 attempts, 2 s / 5 s / 10 s apart, find the device again each time, re-handshake, re-dump
    still failing -> "disconnected" (+ event saying to power-cycle and replug),
    then keep retrying every 30 s
  Commands fail straight away while reconnecting or disconnected (no queueing)