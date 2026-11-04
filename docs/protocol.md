# Spider V 20 MkII protocol notes

Working notes from reverse-engineering the amp over USB-MIDI. Status tags:
**confirmed** = tested on the amp, **inferred** = a guess that fits the data,
**unknown** = not understood yet. Last updated 2026-11-03.

## 1. Connection

- The amp is a class-compliant USB-MIDI device. On the Pi the raw device is
  `/dev/snd/midiC<N>D0`. `<N>` is the ALSA card number and it can change.
  `amidi -l` shows it as `hw:N,0,0`. The Pi code finds it by parsing
  `/proc/asound/cards` (the card named `Spider V 20`) (confirmed).
- Every message is SysEx: starts `F0`, ends `F7`.
- Line 6 header: `F0 00 01 0C 22 05 4D`, then `msg[7]` = channel (0 or 1) and
  `msg[8]` = a counter. Each channel has its own counter.
- Messages are identified by their **shape**: `(length, msg[11], msg[13])`.
- Replies arrive about 4 ms after a request (measured in the app's own startup
  capture, 242 requests, maximum 5.4 ms).

## 2. Session start (handshake)

- `handshake.txt` holds 258 messages recorded from the Spider V Remote app. Send them
  one at a time and read the amp's replies after each. The Pi code reads until the
  line is quiet for 50 ms. The app's capture has about 266 replies in total; ours get
  more, because of the stream in section 7.
- Line 1 is a MIDI Universal Device Inquiry, `f07e7f0601f7`. The amp answers with a
  17-byte identity reply and a 48-byte reply containing the text `L6ImageType:main`
  and `L6Version:2.0.0.0.0`.
- Of the 258 messages, 242 are preset-list requests (shape `(29, 0x0B, 0x06)` x127
  and `(29, 0x0B, 0x0E)` x115). Their replies are the preset-info messages that carry
  the preset names (see section 4). The rest set up the session.
- The app's own startup takes about 21 seconds, with a median 32 ms between messages.
  It always has a reply between two preset-list requests.
- **Dump trigger (confirmed):** handshake line 8 on its own makes the amp send the
  current-preset dump:
  `f000010c22054d010200000b000b0000000400003c007f7f7f7f0000f7`
- The counters in a fresh session start at 0. After the replayed handshake the
  channel-0 counters end at 0x0B, so the Pi's own `seq` starts at 0x0C.
- After an unclean disconnect, a new session's first replies were seen with counters
  such as 0x07 or 0x09, so the amp seems to keep session state (**inferred**). See
  section 9 for the reliability problems.

## 3. Preset dump

A dump is six messages. The first five are 309 bytes, the sixth is a short one
(45 bytes).

| Part | Where |
|------|-------|
| Header | `F0 00 01 0C 22 05 4D`, `msg[7]` = 1, `msg[8]` = a counter shared by the dump, `msg[9]` = chunk index 0 to 5 |
| Payload | `msg[12:-1]` of chunks 0 to 4, joined: 5 x 296 = **1480 bytes** |
| Last chunk | index 5, 45 bytes, not part of the payload so far |

(Older notes said the final message was 29 bytes. In the 2026-11-03 Chime captures it was
45 bytes with `01 08` at msg[10:12]; after a Pi preset select it was 53 bytes with `01 0F`.
Across 13 presets selected from the Pi the last chunk was 21 to 61 bytes, and for
"Vibe 1: Auto Wah" the dump ended at index 4 with a 277-byte chunk. So: every chunk shares
chunk 0's **counter (msg[8])**, the index is at msg[9], and **the dump ends with the first
chunk shorter than 309 bytes**.)

- **Preset name in the dump (confirmed on 4 dumps):** chunk 0, `msg[56]` = name length + 1,
  name starts at `msg[61]`. The payload is 7-bit packed in groups of 8 from `msg[12]`, so
  skip the byte at each position where `(i - 12) % 8 == 0` (for example `Jungle ` 00 `$lash`).
  Implemented in `tools/preset_select.py`.

What is known about the payload:

- The preset name is near the start, 7-bit packed (a 00 byte every 8th character), as
  in preset-info messages: `Chime 1: Class-A`.
- Parameter values are stored in the same 5-byte raw form as the live reports, at least
  for Gain: **payload offset 1175 = (0x2A, 0x25, 0)** on "Chime 1: Class-A"
  (confirmed twice). It held `5160225d3e` (0.4316), then `004000663f` (0.8984)
  after `set drive 0.9`.
- The bytes just before it are `1f 00 00 00 03 00`, which looks like a record header.
  If the record number is the wire id minus 6 (0x25 - 6 = 0x1f), the dump is
  numbered 6 lower than the wire ids. **Only one data point. Unconfirmed.**
- Values tied to the physical Tone, reverb and FX knobs (see section 7) differ from one
  capture to the next without any change from us, so ignore them when diffing dumps.
  In the Chime captures these were around offsets 412-414, 1064-1091 and 1141-1193.
- The Tone values in the dump look different from the live reports (for example
  `1a 15 02 15 3f`), so they are **not decoded**.
- Candidate offsets matched by value to the exported preset (single matches in one
  capture, stable between two captures, **unconfirmed**): 685 = amp volume, 790 =
  FX1 Gain, 967 = FX3 Time, 1001 = FX3 "Eko dist", 1400 = EQ Low, 1423 = EQ LMid.
- The amp's preset **type** (amp model, effect models) has not been located yet.
  Expect numeric ids from the `.models` files (section 10).
- A dump is not always returned. In the four Chime captures of 2026-11-03 it arrived in
  two (the first baseline and the "Drive" capture) and not in the other two (see
  section 9).

## 4. Messages from the amp

| Shape (len, msg[11], msg[13]) | Extra check              | Meaning                    | Status |
|-------------------------------|--------------------------|----------------------------|--------|
| (45, 0x07, 0x04)              |                          | parameter report           | confirmed |
| (45, 0x07, 0x03)              | msg[35] == 1, msg[26] != 0x7F | Save pressed          | confirmed |
| (45, 0x07, 0x03)              | msg[26] == 0x7F          | status: arrives about 2 s after each preset change ("preset loaded"?) | inferred |
| (45, 0x07, 0x03)              | anything else            | preset knob changed; position = (msg[26] - 8) % 16 (see section 11). Called "heartbeat" in older notes | confirmed |
| (37, 0x0F, 0x05)              |                          | tap tempo                  | confirmed |
| 50 to 99 bytes, msg[13] == 1  |                          | preset info (name)         | confirmed |
| (29, 0x0B, 0x01)              |                          | sync-like message with a counter; follows each status message | ignore |
| 309 bytes, msg[13] == 1       |                          | dump chunk, **not** preset info | section 3 |

### Parameter report (45 bytes)

- Address = `(msg[22], msg[26], msg[27])` = (block, id, sub).
- Value = 5 bytes at `msg[35:40]`.
- The same id in a different block is a different parameter (for example 0x24 is
  Volume in block 0x74 but a Tone part in block 0x2A). Always key on the full address.

### Value decode (amp reports)

Value bytes `v0..v4`:

1. `flag = v1 & 0x20`
2. `third = v3`, with `0x80` added if the flag is set
3. `top = v4`
4. The float is `struct.unpack('<f', bytes([0, 0, third, top]))`

The result is 0.0 to 1.0 in 256 linear steps.

### Tap (37 bytes)

BPM = `decode_value(msg[26:31]) * 2` (confirmed by user tests).

### Save (45 bytes)

Pressing the Save button gives shape `(45, 7, 3)` with `msg[35] == 1` and
`msg[26] != 0x7F` (confirmed).

### Preset info

- Name = printable ASCII of `msg[49:-1]`. Names are 7-bit packed, so every 8th byte is
  a 00 and is dropped by the printable filter.
- The handshake returns the whole list of names (factory presets plus `User 1` to
  `User 4`).
- Older notes said the amp announces the current preset about every 5 seconds. That was
  seen while the Tone/Reverb jitter stream was running (section 7). With a quiet amp
  (2026-11-03, knobs at minimum) a preset-knob click sent **no** preset-info message,
  only the preset-change event and the status message. So announcements seem to follow
  parameter activity, not preset changes (**inferred**).
- `msg[40]` is a "fingerprint" byte per preset. It is not unique and not an
  "edited" flag. **Unknown.**
- The amp never reports the knob position, only the preset name.

## 5. Parameter blocks and ids

`msg[22]` selects the block.

| Block | Meaning |
|-------|---------|
| 0x74  | Panel: the physical controls |
| 0x2A  | Amp block |
| 0x19 / 0x1B / 0x1D | FX1 / FX2 / FX3 effect blocks (ids depend on the effect model in the preset) |
| 0x1F  | Reverb effect block |
| 0x6C  | Tap (hold) |

### Known parameters (block, id, sub)

| Address          | Name           | Notes |
|------------------|----------------|-------|
| (0x74, 0x24, 3)  | Volume         | physical knob. A set of 0 showed up as 0 on the next connect. |
| (0x74, 0x20, 3)  | Reverb         | physical knob |
| (0x74, 0x1A, 3)  | FX Knob (FX1)  | "Smart FX" knob when FX1 is on |
| (0x74, 0x1C, 3)  | FX Knob (FX2)  | when FX2 is on |
| (0x74, 0x1E, 3)  | FX Knob (FX3)  | when FX3 is on |
| (0x74, 0x48, 3)  | FX1 button     | colour suggests Stomp (inferred) |
| (0x74, 0x47, 3)  | FX2 button     | colour suggests Mod (inferred) |
| (0x74, 0x46, 3)  | FX3 button     | colour suggests Delay (inferred) |
| (0x2A, 0x25, 0)  | **Gain** or **Drive** | see below (confirmed by setting it) |
| (0x2A, 0x26, 0)  | **Drive** (on amps whose control is named "Drive") | see below |
| (0x2A, 0x21, 0)  | Tone part, about Bass | inferred from the exported Chime preset |
| (0x2A, 0x23, 0)  | Tone part, about Mid  | inferred |
| (0x2A, 0x24, 0) and (0x2A, 0x27, 0) | Tone parts, Treble and Presence in some order | identical values on Chime, so the order is unknown |
| (0x2A, 0x02, 0)  | not a float | value changes with knob activity. **Unknown.** |
| (0x1F, 0x0A, 0), (0x1F, 0x46, 2), (0x1F, 0x7A, 1) | reverb block values | sub 0, 2 and 1 respectively; meaning not mapped |
| (0x6C, 0x72, 3)  | Tap (hold)     | |

### Gain versus Drive (confirmed on three presets, inferred in general)

The amp's main gain control has two different ids depending on the control's symbol
name in `amps.models`:

| Preset | Amp | Control symbol | Wire id |
|--------|-----|----------------|---------|
| Chime 1: Class-A | 1967 Class A-30 Top Boost | `Gain` | 0x25 |
| Crunch 2: Pasadena | 1968 Plexi Variac'd | `Gain` | 0x25 |
| Jungle $lash | Line 6 Chemical X | `Drive` | 0x26 |

So the id seems to belong to the **symbol name**, not to the amp (**inferred** from three
presets). A phone control for "gain" must send to whichever id the current amp's symbol
uses.

### Caveats

- **Tone has no single id.** One physical Tone control moves ids 0x21, 0x23, 0x24 and
  0x27 together in block 0x2A.
- The FX knob's panel id depends on which FX slot is switched on.
- The ids of the FX1/2/3 blocks depend on the effect model in the preset.
- In block 0x2A msg[23] is 0; elsewhere it is 3.

## 6. Value encodings

### Amp reports

See section 4.

### For sets (what the Pi sends)

`raw5 = [0, 0, (0x40 if third & 0x80 else 0), third & 0x7F, top]`, where `third` and
`top` are bytes 2 and 3 of the little-endian float. All data bytes must be below 0x80.
Test vectors (app captures; the decoder maps these to the value shown):

| Raw 5 bytes  | Value    |
|--------------|----------|
| `5022405d3e` | about 0.4316 |
| `6033400c3e` | about 0.2734 |
| `7b1800023f` | about 0.5078 |

0.9 encodes as `00 00 00 66 3f`. After `set drive 0.9` the amp reported `004000663f`
(0.8984), and the dump held the same bytes (confirmed).

## 7. What the amp streams (important for the software)

- **With nobody touching the amp, our session receives about 59 parameter reports per
  second** (14,772 reports in 250 s, 2026-11-03 idle capture). They are the same ten
  parameters in two round-robin groups:
  - amp group: (2A,21), (2A,23), (2A,24), (2A,25), (2A,27), (2A,02), each 1,684 times
  - reverb/panel group: (1F,0A,0), (1F,46,2), (1F,7A,1), (74,20,3), about 1,100 to
    1,200 times each
- The values jitter by about 0.01 (4 to 7 distinct values per parameter). Gain
  (2A,25) never changed. (2A,02) is not a float.
- **Cause (confirmed 2026-11-03): the physical Tone and Reverb knobs jittering.** The
  idle capture above was taken right after a power-cycle, so it is not stale session
  state. With Tone and Reverb turned fully down (against the end stop), the same idle
  test produced **no** messages at all. Each group is one knob plus the values it
  drives: Reverb = (74,20,3) and the 0x1F block, Tone = the 0x2A group (Gain and
  (2A,02) are re-sent with it even though Gain does not change).
- The amp group only started at 16:51:07, just after the preset click in that capture;
  the reverb group ran from the first second.
- The app's captures were quiet probably because its knobs were not sitting on a step
  boundary. This is not a session problem.
- Design consequences: always keep reading, treat reports as state, not events, and use
  a change threshold of about 0.02 before showing a change.

## 8. Sending to the amp

### Set a parameter: two messages

1. **Begin** (29 bytes):
   `F0 00 01 0C 22 05 4D 00` + `SEQ 00 00 07 00 0A 00 00 00 10` + 10 zero bytes + `F7`
2. **Set** (37 bytes):
   `F0 00 01 0C 22 05 4D 00` + `SEQ+1 00 00 0F 00 <block> <sub> 00 00 <id> <sub> 00 <unk> 00 04 00 00 00`
   + 5 value bytes + 5 zero bytes + `F7`
   - Block at msg[13], sub at msg[14] **and** msg[18], id at msg[17], value at
     msg[26:31]. (Older notes said msg[15]; that was wrong.)
   - msg[20] (`<unk>`) takes values 1 to 3 in the app's captures. **Unknown.** The Pi
     code sends 1, which works for Drive.
   - `SEQ` starts at 0x0C and steps by 2.

### Status of sets

| Set | Result |
|-----|--------|
| Drive/Gain (0x2A, 0x25 / 0x26, sub 0) | **confirmed** by ear, and by the amp's report and dump |
| Volume (0x74, 0x24, sub 3) | probably works (reported 0 at the next connect) |
| Reverb (panel 74:20:3 and block 1F:7A:1) | no visible effect. **Unconfirmed** |
| Sub values other than 0 and 3 | unconfirmed (no capture of the app doing it) |

Whether a set appears in the live stream (section 7) still needs a test.

### Preset select

A 29-byte message with one value byte:
`f000010c22054d0102 00 00 0b 00 0d 00 00 00 04 00 00 00 00 <value> 00 00 00 00 00 f7`
followed by the dump request (section 2), then further messages.

Values seen: `08` loaded "Jungle $lash" and `04` loaded "Chime 1: Class-A", so the value is
probably an index into the amp's preset list.

**Sent from the Pi (2026-11-03, `tools/preset_select.py`, `captures/preset_select_2.txt`):**
preset select works (**confirmed**). The dump request right after it returns the newly
loaded preset. Values and names read from those dumps:

| Value | Preset | Value | Preset |
|-------|--------|-------|--------|
| 0 | Bass | 7 | Crunch 2: Pasadena |
| 1 | Acoustic | 8 | Jungle $lash |
| 2 | Clean 1: US Double | 9 | Chunk 2: Phat Chunk |
| 3 | Clean 2: Jazz Chorus | 10 | Insane 1: Lunatic |
| 4 | Chime 1: Class-A | 11 | Insane 2: Criminal |
| 5 | Chime 2: Echoes | 12 | Vibe 1: Auto Wah |
| 6 | Sugar Skull | 13 | Vibe 2: Rotary |
| 14 | Ambient 1: Black Hole | 18 | Brit J-900 Dist |
| 15 | Ambient 2: Glass | 19 | Brit JTS-45 |
| 16 | Brit Plexi 45 | 20 | 90s SLO |
| 17 | Brit J-800 | | |

This is the order of the handshake's preset list, and 4 and 8 match the app captures.
The list continues past 15, so the amp has more presets than the knob's 16 positions;
how far it goes (the handshake list has well over 100 names) has not been tried.
Which value each knob position loads: see section 11.
A select sends no preset-change event; only the (29, 11, 1) message and the status
message came back besides the dump.

### Save command

**Not found.** Needs a new capture of the app saving a spare user preset.

## 9. Reliability: the amp's "wedge"

Observed on 2026-11-03 (causes are not proven):

- After repeated connect/disconnect cycles the amp stops accepting writes. Symptoms: a
  write times out part-way (`4 of 29 bytes unsent`), `dmesg` shows `rawmidi drain
  error` and `urb status -32` before a USB disconnect, and the amp's own buttons stop
  working. Power-cycling the amp and replugging USB fixes it.
- The Pi code's handshake is not a flood: it reads after each send, and the amp
  replies in about 4 ms. Pacing is similar to the app's.
- Of four Chime captures, two contained the dump (the first baseline and the "Drive"
  capture); the other two (888 and 534 messages) did not. What differed between those
  sessions (power-cycle, earlier failures) was not recorded.
- A truncated write leaves the amp part-way through a SysEx message (**inferred** as
  a cause).
- Power is fine (`vcgencmd get_throttled` = 0x0).

Working rules until this is understood:

1. Use **one long-lived connection** (the console, later the Flask server). Do not
   script repeated connect/handshake cycles.
2. **Never stop reading** (section 7).
3. Drain stale bytes when the port opens, and close in a `finally`.
4. After a wedge, power-cycle the amp and replug USB before trying again.

## 10. Spider V Remote app data (`C:\Program Files (x86)\Line6\Spider V Remote\res`)

These are the app's own files, used here only as reference. **Do not commit them or
`login.json` (it holds a Line 6 login token).**

- `amps.models`, `cabs.models`, `stomps.models`, `delay.models`, `mod.models`,
  `wahs.models`, `reverbs.models`, and others: JSON arrays, one entry per model type.
  Fields: `symbolicID` (for example `ClassA30TopBoost`), numeric `id`, `category`,
  `name`, `icon`, and `params[]` (`name`, `symbolicID`, `default`, `min`, `max`,
  `valueType` 0 int / 1 float / 2 bool, `persist`, `tweak`). This is the
  list of controls to show for each type, and explains Gain versus Drive.
  Examples: ClassA30TopBoost = 131117, BritPlexiVariac = 131102, Line6ChemicalX = 131082.
- Preset (tone) files: `.svl6p`, JSON with `schema: "L6Preset"`, `version: 5`, device
  2228229, and a `tone` object with sections `amp`, `cab`, `compressor`, `eq`,
  `fx1`, `fx2`, `fx3`, `gate`, `global`, `reverb`, `volume`, `wah`. Each has `@model`
  and its parameters by symbol name. `global` has `@tempo`, `@tweakgroup` and
  `@tweakparam` (what the FX knob drives, for example `fx3` / `@mix`). This is the
  import/export format.
- `defaultSymbolTable*.bin` (611 entries, or 629 in the TT/FX100/Dio variants):
  `u32 count, u32 size`, then `count` records `(offset, hash, length)` into a string
  area at byte `8 + 12*count`. The indices do **not** match the wire ids, so they are not
  needed.

## 11. Preset knob positions

### The preset-change event (confirmed 2026-11-03, `captures/preset_clicks.txt`)

- Each click of the preset knob sends one or more `(45, 7, 3)` messages with a value in
  `msg[26]`, then the `0x7F` status message about 2 s later.
- **Position = (msg[26] - 8) % 16.** Starting at position 0 after a power-cycle and
  clicking once round, the settled values were 9, 10, 11, 12, ... 15, 0, 1, ... 8.
- **Contact bounce:** while the knob moves, the value flickers, and the stray values
  are the 4-bit complement of a real one (`r ^ 0x0F`): 0x0A/0x05, 0x0B/0x04,
  0x0E/0x01, 0x0F/0x00. On two clicks the last value before the status was the
  complement, so the last value alone is not reliable.
- Working rule (used in `tools/console.py`): collect the values for one click until
  the status message; consider each value and its complement; pick the position that
  is one step from the previous position. If none is, use the last value.
  Checked against the 16 clicks in `preset_clicks.txt` only.
- The amp does not send the preset name on a click (section 4).

### Old position → name table (2026-10-30)

Recorded before the bounce was known, assuming one click per name announcement.
The repeated names (positions 2/15, 4/13, 5/12) may be bounce errors, so **re-check this
table** before relying on it.

| Pos | Preset                | Pos | Preset              |
|-----|-----------------------|-----|---------------------|
| 0   | Crunch 2: Pasadena    | 8   | Ambient 2: Glass    |
| 1   | Jungle $lash          | 9   | Bass                |
| 2   | Sugar Skull           | 10  | Acoustic            |
| 3   | Insane 1: Lunatic     | 11  | Clean 1: US Double  |
| 4   | Chime 1: Class-A      | 12  | Clean 2: Jazz Chorus |
| 5   | Clean 2: Jazz Chorus  | 13  | Chime 1: Class-A    |
| 6   | Vibe 2: Rotary        | 14  | Chime 2: Echoes     |
| 7   | Ambient 1: Black Hole | 15  | Sugar Skull         |

## 12. Open questions

- The position → preset name table, re-recorded with the bounce rule (section 11).
- The cause of the wedge, and a reliable way to get the dump every time.
- Where the amp model and effect models are stored in the dump, and the layout of the
  rest of the dump (record numbering, Tone values).
- Whether the wire id always follows the symbol name (section 5).
- The Tone ids: which of 0x24 and 0x27 is Treble and which is Presence.
- (2A,02), and what the status message means exactly.
- Preset fingerprint byte (msg[40]) and msg[20] in set messages.
- Preset-select value mapping, and the Save command.
- Whether sets in the panel block (Volume, Reverb, FX) work, and sets with sub other
  than 0 and 3.
- Whether a set shows up in the live stream.

## 13. Hardware notes

- Power the Pi from a proper 5 V 3 A supply. Earlier under-voltage caused reboots.
  Check with `vcgencmd get_throttled` (0x0 means fine).