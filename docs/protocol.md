# Spider V 20 MkII protocol notes

Working notes from reverse-engineering the amp over USB-MIDI. Status tags:
**confirmed** = tested on the amp, **inferred** = a guess that fits the data,
**unknown** = not understood yet. Last updated 2026-11-06.

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
  and `(29, 0x0B, 0x0E)` x115, preset index at `msg[22]`). Each gets one preset-entry
  reply with that preset's name: section 4, "Preset list". The rest set up the session.
- The app's own startup takes about 21 seconds, with a median 32 ms between messages.
  It always has a reply between two preset-list requests.
- **Dump trigger (confirmed):** handshake line 8 on its own makes the amp send the
  current-preset dump:
  `f000010c22054d010200000b000b0000000400003c007f7f7f7f0000f7`
- The counters in a fresh session start at 0. After the replayed handshake the
  channel-0 counters ended at 0x0B in the first captures, so the Pi's own `seq` starts
  at 0x0C. On 2026-11-06, two runs straight after a power-cycle ended at 0x07 and 0x08
  instead, so the end point varies. It doesn't matter for sets (section 8).
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
### Parameters in the dump (2026-11-06, `tools/dump_params.py`, `captures/dump_params_5.txt`)

Method: on presets 4, 8, 0 and 14, set each parameter to 0.5 then 0.75 and dump after
each. Offsets below are into the **unpacked** data (each 309-byte chunk unpacked like a
preset-list entry, section 4, then joined: 5 x 259 = 1295 bytes). Two dumps with no set
in between were identical on all four presets, so nothing changes on its own while the
knobs are left alone.

- **The packing (confirmed 2026-11-06, `captures/dump_bits.txt`):** in each group of 8
  bytes from `msg[12]`, the first byte holds the top bits of the next 7, **most
  significant first: data byte k (0 to 6) takes bit `6 - k`** (`0x40 >> k`). Unpack each
  309-byte chunk on its own (37 groups, 259 bytes) and join them.
  - Found by setting 0.5 then 1.0 (`3f800000`, one extra top bit) on 6 parameters x 4
    presets: each time exactly one top-byte bit flipped, in the value's own group, and
    it was bit 6 - k for k = 0, 1, 3, 4 and 5.
  - Checked: every record header then has no stray 0x80s, every set value reads back,
    and `drive_min.txt` / `drive_max.txt` read exactly 0.0 / 1.0.
  - The same rule is already in the live-report and set-value code (section 7): in a
    5-byte value the first byte is the top byte, and the 0x80 of value byte 1 is its
    bit 5 (`0x20` in `decode_value`), or bit 6 (`0x40`) for value byte 0 in
    `encode_set_value`.
  - The earlier attempts failed because they assumed 0.5 is stored as `00 00 00 3f`.
    It isn't (next point).
- **The amp fills in the low bytes of a set value:** 0.5 is stored as `00 80 00 3f`
  (0.502), 0.75 as 0.752 and 1.0 as 1.0039. A set only carries the top 16 bits of the
  float (section 8), and the amp sets the next bit (half a step, about 0.002). Compare a
  dump to a sent value with a tolerance of about 0.005.

### The dump's layout: blocks of records (confirmed 2026-11-07, 17 dumps)

Checked on every dump captured: the 4 presets in `captures/dump_params_5.txt` and the 13
in `captures/preset_select_2.txt`. All parse the same way, into the same 13 blocks in the
same order.

1. **The data stream:** unpack each 309-byte chunk (top bits MSB-first, above) and keep
   the **first 256** of its 259 bytes; the last 3 are padding. Join the chunks. (Keeping
   all 259 puts 3 stray zero bytes into every record that crosses a chunk boundary.
   That's why some records looked "not understood" in the table below.)
2. **Records are 10 bytes:** `id, sub, 00, flag, type, 00`, then a 4-byte little-endian
   value. `type` 03 = float, 01 = whole number (0/1 for on/off), 02 = a choice (whole
   number), 07 = an id. `flag` 0x80 marks a block's info records.
3. **A block** is 3 info records (flag 0x80), then its parameter records:
   - `03`, type 07: which block, as `id | sub << 8` (for example 0x002A = block 2A sub 0,
     0x0374 = block 74 sub 3). This is the wire block of the parameters inside.
   - `05`, type 07: the block's "kind". For the amp block it differs per preset, so it's
     probably the **amp model id** (Chime 0xDC, Jungle $lash 0xB0, Bass 0xBF). Not checked
     against the `.models` files (section 10).
   - `06`, type 02: how many parameter records follow.
4. **The blocks, in order** (number of records in brackets, which varies with the model
   for some):

   | Block | Records | Holds |
   |---|---|---|
   | 74:3 | 25 | the panel: FX knobs and switches, Reverb, Volume (ids 0x26 to 0x3E) |
   | 5E:2 | 2 | ? |
   | 04:3 | 3 | ? |
   | 0C:3 | 1 | ? |
   | 19:3 | 2 to 5 | an effect? (kind varies) |
   | 1B:3 | 2 to 5 | an effect? |
   | 1D:3 | 5 | an effect? |
   | 1F:3 | 2 or 3 | reverb? |
   | **2A:0** | **5** | **the amp: ids 0x1C, 0x1D, 0x1E (Tone part), Drive, 0x20** |
   | 21:3 | 1 | ? |
   | 22:3 | 0 | ? |
   | 23:3 | 2 | ? |
   | 25:3 | 7 or 8 | ? (runs into the short last chunk) |

5. **The amp block's 4th record is the Drive the preset uses:** id `0x1F` (= wire
   2A:25, "Drive") on Chime, `0x33` (= wire 2A:26, "Drive (alt)") on Jungle $lash, Bass
   and Ambient 1. Record ids are numbered per block and repeat across blocks (0x1F
   appears in 19:3, 23:3 and 25:3 too), so always look in the right block first.
6. **Record id to wire id**, where known from `tools/dump_params.py` (block 74:3 and
   2A:0 only):

   | Block | Record | Wire | Name |
   |---|---|---|---|
   | 74:3 | 0x26 / 0x2A / 0x2E | 1A / 1C / 1E | FX Knob (FX1 / FX2 / FX3), float |
   | 74:3 | 0x28 / 0x2C / 0x30 | 48 / 47 / 46 | FX1 / FX2 / FX3 on/off, whole number |
   | 74:3 | 0x32 | 20 | Reverb, float |
   | 74:3 | 0x3C | 24 | Volume, float |
   | 2A:0 | 0x1E | 24 | Tone (part), float |
   | 2A:0 | 0x1F | 25 | Drive, float (some amp models) |
   | 2A:0 | 0x33 | 26 | Drive (alt), float (the other amp models) |
   | 2A:0 | 0x20 | 27 | Tone (the other id), float |

   0x1C and 0x1D in the amp block, and the rest of the panel block (0x27, 0x29, 0x2B,
   0x2D, 0x2F, 0x31, 0x33 to 0x3B, 0x3D, 0x3E), aren't matched to wire ids yet.
7. Values in the amp block before any set, read this way, match the live reports: Drive
   on Chime 0.433 (live report 0.4316).

### Names: the amp's symbol table (confirmed 2026-11-07)

**The Spider V MkII's names are `defaultSymbolTable_Parker.bin`** (in the app's `res`
folder, section 10; format there). Its symbols are numbered from 0, and those numbers
are the amp's ids:

- **Block kinds are model names** (the `05` info record, layout point 3). All 11 amp-model
  ids noted in the app (`captures/windows/models.txt`) sit at exactly their position in
  the table, for example 0xDC = `ClassA30TopBoost`, 0xB0 = `Line6ChemicalX`, 0xBF =
  `L6TubePreamp`. The symbol is the model's `symbolicID` in `amps.models` (and in
  `stomps`/`mod`/`delay`/`reverbs`/`fixed`.models for the other blocks), which gives its
  display name. So every block in a dump says which model it is:

  | Block | Kinds seen | What it is |
  |---|---|---|
  | 74:3 | `SpiderVGuitarFlow` | the panel / signal chain |
  | 5E:2 | `Gate` | noise gate |
  | 04:3 | `VolumePedal` | volume pedal |
  | 0C:3 | `Line6Vetta`, `Weeper`, `Fassel`, `Chrome` | wah |
  | 19:3 | `Screamer`, `BassOverdrive`, `VettaComp`, `RedComp`, `L6BoostPlusEQ`, ... | FX1 (stomp) |
  | 1B:3 | `AnalogChorus`, `OptoTremolo`, `Phaser`, `JetFlanger`, `AutoWah`, ... | FX2 (modulation) |
  | 1D:3 | `L6DigitalDelay`, `TapeEcho`, `TubeEcho`, `AnalogDelay`, ... | FX3 (delay) |
  | 1F:3 | `SmallRoom1`, `LuxSpring`, `VintagePlate`, `ReallyLargeHall`, ... | reverb |
  | **2A:0** | `ClassA30TopBoost`, `Line6ChemicalX`, ... | **the amp** |
  | 21:3 | 0 (none) | ? |
  | 22:3 | `2x12ClassAStudio57OnAxis`, `4x12TreadplateStudio421`, ... | cab and mic |
  | 23:3 | `SharcPodFixedComp` | compressor |
  | 25:3 | `ParaGraphic4_band` | 4-band EQ |

- **Wire ids in namespace 0** (`msg[18]` = 0 in a set, section 8) are symbol numbers too:
  0x21 `Bass`, 0x23 `Mid`, 0x24 `Treble`, **0x25 `Gain`**, **0x26 `Drive`**, 0x27
  `Presence`, 0x02 `Level`, 0x07 `Low`, 0x0A `Decay`. So:
  - "Drive" (2A:25) in parameters.py is really **Gain**, and "Drive (alt)" (2A:26) is
    **Drive**. Each amp model has one (`amps.models`): Chime's Class A-30 Top Boost has
    Gain, Jungle's Chemical X has Drive.
  - "Tone (part)" (2A:24) is **Treble**, and 2A:27 is **Presence**. **Bass is 2A:21**
    (not 0x22) and **Mid 2A:23**.
  - The ignored report "(2A,02)" (section 7) is the amp's **Level**.
  - Ids in namespaces 1, 2 and 3 are numbered differently (0x60 in the gate is its
    threshold, not the symbol `LoMid`); they are named from the app capture (section 8).
- **Dump record ids are the parameters' "State" symbols** (namespace in the record's
  second byte, 0 here): 0x1C `BassState`, 0x1D `MidState`, 0x1E `TrebleState`, 0x1F
  `GainState`, 0x20 `PresenceState`, 0x33 `DriveState`. So a record names the parameter
  it holds: drop "State".
- The panel block (74:3) has 4 records per FX slot (0x26-0x29 FX1, 0x2A-0x2D FX2,
  0x2E-0x31 FX3): the FX knob (float), a whole number, on/off, and a choice; probably
  `FXnMix`, `FXnPost`, `FXnEnable` and `FXnMixType`.
- The other tables (TT, Dio, FX100, AEON, Firebird, the default one) are for other
  Line 6 products; an offset of 19 made some amp names fit by chance.

### Offsets found by `tools/dump_params.py` (2026-11-06/07)

Superseded by the layout above, but kept as the evidence for its record table. Offsets
are into the 259-bytes-per-chunk view (1295 bytes).

  | Parameter (wire id) | Record id | Header seen | Offsets (presets 4 / 8 / 0 / 14) |
  |---|---|---|---|
  | Drive (2A:25:0) | 0x1F | `1f 00 00 00 03 00` | 1028 / - / - / - |
  | Drive (alt) (2A:26:0) | 0x33? | `33 00 00 00 03 00` on preset 14; `00 03 00 00 00 00` on 8 and 0 (not understood) | - / 1037 / 1038 / 1020 |
  | Volume (74:24:3) | 0x3C | `3c 03 00 00 03 00` | 460 / 456 / 447 / 462 |
  | Reverb (74:20:3) | 0x32 | `32 03 00 00 03 00` | 360 / 356 / 347 / 362 |
  | FX Knob (FX1) (74:1A:3) | 0x26 | `26 03 00 00 03 00` | 237 / 233 / 224 / 239 |
  | FX1 (74:48:3) | 0x28 | `28 03 00 00 01 00` on preset 0; others unclear | 260 / ? / 244 / 262 |
  | FX Knob (FX2) (74:1C:3) | 0x2A | `2a 03 00 00 03 00` | 280 / 276 / 267 / 282 |
  | FX2 (74:47:3) | 0x2C | `2c 03 00 00 01 00` | 300 / 296 / 287 / 302 |
  | FX Knob (FX3) (74:1E:3) | 0x2E | `2e 03 00 00 03 00` | 320 / 316 / 307 / 322 |
  | FX3 (74:46:3) | 0x30 | `30 03 00 00 01 00` | 340 / 336 / 327 / 342 |
  | Tone (part) (2A:24:0) | 0x1E | `1e 00 00 00 03 00` | 1018 / 1024 / 1025 / 1010 |
  | 2A:27:0 (Tone?) | 0x20? | `20 00 00 00 03 00` on 8 and 0 | 1041 / 1047 / 1048 / ? |
  | Reverb (mix) (1F:7A:1) | - | - | nothing changed on any preset |

  (FX2 to 2A:27:0: 2026-11-07, `captures/dump_params.txt`. All read back as set except
  2A:27:0 on preset 14, where one byte changed but no float matched.)
  "-" = the set changed nothing. The "not understood" headers and FX1's odd offsets are
  records crossing a chunk boundary in this 259-byte view (see the layout above). FX1 is
  a whole number (type 01), so setting it to 0.5 doesn't read back as 0.5.
- Values found before any set, for the record (MSB-first): Drive on Chime 0.433 (the
  live report said 0.4316); Volume 0.592 / 0.240 / 0.702 / 0.700 and Reverb 0.204 /
  0.292 / 0.501 / 0.478 on presets 4 / 8 / 0 / 14; FX Knob (FX1) 1.0 and FX1 0.0 on all four.
- **Drive or Drive (alt) depends on the preset** (**confirmed** on 4 presets): Chime
  (preset 4) only responds to 0x25; Jungle $lash, Bass and Ambient 1 only respond to
  0x26. The dump says which: the amp block's Drive record (layout, point 5).
- The amp model is probably the amp block's "kind" (layout, point 3). The effect models
  may be the other blocks' kinds. Not matched to the `.models` files yet.
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
| 45 to 77 bytes, msg[13] == 1  | `msg[7]` == 1            | preset-list entry (name), in reply to a preset-list request | confirmed |
| (29, 0x0B, 0x01)              | `msg[7]` == 0            | the amp's answer to a set (section 8); also seen around status messages | ignore |
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

### Preset list (decoded 2026-11-06 from `captures/handshake_replies.txt`)

The handshake asks for every preset's name with two kinds of request. Both are
29 bytes, channel 1, with the preset index at `msg[22]`:

`f000010c22054d01 <ctr> 00 00 0b 00 <kind> 00 00 00 04 00 00 00 00 <index> 00 00 00 00 00 f7`

| Kind (`msg[13]`) | Indexes asked | Reply layout | What it lists |
|------------------|---------------|--------------|---------------|
| `0x06` | 0 to 127, except 4 (127 requests) | short | all 128 preset slots, ending with `User 1` to `User 4` at 124 to 127 |
| `0x0E` | 0 to 114 (115 requests) | long | indexes 0 to 114 only |

**Decoding a reply (confirmed: all 240 entries in the capture fit one of the two layouts).**

1. Unpack the 7-bit payload. From `msg[12]` up to the `F7`, take groups of 8 bytes. The
   first byte of a group holds the top bits of the next 7, most significant first: data
   byte k (0 to 6) takes bit `6 - k` (`0x40 >> k`). Output the 7 bytes, adding `0x80`
   where the bit is set. This is the same packing as the dump, where it is confirmed
   (section 3). The "skip every 8th byte" rule there is this with the top bits ignored.
   (Until 2026-11-06 this said bit k → byte k. That gives the same names, because
   preset-list entries have no top bits set in the bytes that matter, so both rules fit
   all 240 entries.)
2. In the unpacked bytes `u`:

   | Layout | Length byte | Name starts | Check | Raw message offsets |
   |--------|-------------|-------------|-------|---------------------|
   | short | `u[12]` = name length + 1 | `u[16]` | `u[4] == u[12] + 8` | length `msg[26]`, name from `msg[31]` |
   | long  | `u[28]` = name length + 1 | `u[32]` | `u[4] == u[28] + 24` | length `msg[45]`, name from `msg[49]` |

   The name is plain ASCII with zero padding after it. In the long layout, `u[12:15]` and
   `u[20:26]` hold 9 more bytes per preset (an id or checksum?). **Unknown.** `u[0]` is
   always 1.
3. A name of 12 characters or fewer gives a **45-byte** message; longer names give 53,
   61, 69 or 77 bytes.

**Matching replies to indexes: by handshake line.** The reply's counter (`msg[8]`) only
matches the request's counter when the amp's counters are in step with the recording.
In 3 of 4 captures they were not, so counter matching gave wrong names. The reply
arrives within about 4 ms (section 1), so the replies read after sending line *n* belong
to line *n*'s request. Flattening all the handshake replies into one list loses this.

**What the lists hold (from the one clean capture):**

- The two lists agree on all 112 indexes they share.
- 0 to 20 match the preset-select table (section 8): **list index = select value**
  (inferred for 21 and up).
- The short list had no reply for 0 and 34 (34 was also missing in `chime_B0.txt`), and 4
  is never asked for. The long list covers all three (Bass, Chime 1: Class-A, Mood), so
  **merge the two lists** to get every name.
- 115 to 123 in the short list: DirtyAcoBlues, Fluff Clean, Fluff Big Chug, Clean Your
  Room, Dirt Street, Dub-ya Push, Sugar Skull, Low Rez Fred, Plateau of Leng. These are
  not in the long list. Why the long list stops at 114 is **unknown**.
- Old `classify` (50 to 99 bytes, printable bytes of `msg[49:-1]`) read the long layout
  correctly only by chance, missed every name of 12 characters or fewer, and turned
  short-layout names into fragments such as `orus` and ` Hole`.

**Other notes:**

- Older notes said the amp announces the current preset about every 5 seconds. That was
  seen while the Tone/Reverb jitter stream was running (section 7). With a quiet amp
  (2026-11-03, knobs at minimum) a preset-knob click sent **no** preset-list entry,
  only the preset-change event and the status message. So the entries seen outside
  the handshake seem to follow parameter activity, not preset changes (**inferred**).
- `msg[40]` (old "fingerprint" byte) is inside the packed payload, so it is not a field
  by itself.
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
   - `SEQ` starts at 0x0C and steps by 2. The amp doesn't seem to check it
     (**confirmed** for Drive, 2026-11-06, `captures/seq_check.txt`): sets numbered
     0x0C, 0x09 and 0x0B all worked while the amp's own counter was at 0x08 to 0x0D.

### Status of sets

| Set | Result |
|-----|--------|
| Drive/Gain (0x2A, 0x25 / 0x26, sub 0) | **confirmed** by ear (again 2026-11-06) and by the dump. No report comes back (below) |
| Drive (alt) (0x2A, 0x26, sub 0) | **confirmed** by the dump: the drive for presets 8, 0 and 14, where 0x25 does nothing (section 3) |
| Volume (0x74, 0x24, sub 3) | **confirmed** by the dump on 4 presets (section 3) |
| Reverb (panel 74:20:3) | **confirmed** by the dump on 4 presets (section 3) |
| Reverb (block 1F:7A:1) | changes nothing in the dump on 4 presets. **Probably not a settable parameter** |
| FX1 to FX3 (74:48 / 47 / 46:3) and their FX knobs (74:1A / 1C / 1E:3) | **confirmed** by the dump on 4 presets (section 3) |
| Tone (part) (2A:24:0) and 2A:27:0 | **confirmed** by the dump; which is Treble and which is Presence isn't known |
| Sub values other than 0 and 3 | unconfirmed (no capture of the app doing it) |

### Two sets in a row can stop all sets (2026-11-07, `captures/amp_survey_2.txt`)

`tools/amp_survey.py` sent Drive as both ids, 0x25 then 0x26, straight after each other
(no wait for an answer), on Chime then Jungle $lash:

- The first pair got **one** answer (the 29-byte message) and its status message, and
  Chime's Drive (0x25) changed to 0.1.
- After that, **no set worked and none was answered**: the next pair on Chime, and both
  pairs on Jungle $lash after a preset select. The dump showed the old values, and
  nothing changed by ear. Selects, dumps and knob events still worked.
- The run before it (`captures/amp_survey.txt`) did the same, and a new handshake made
  sets work again.
- In `tools/dump_params.py`, sets of the unused Drive id did no harm, but there each set
  was 0.5 s and a dump apart.

**Cause (confirmed 2026-11-07, `tools/set_pace.py`, `captures/set_pace.txt`, on Chime with
a new handshake before each case):**

| Case | Result |
|---|---|
| Two sets, each sent after the previous one's answer | both worked, one answer each |
| Two sets of the same id (0x25) with no wait | the **first** worked and was answered; the second was dropped |
| ...then a set 1 s later, 5 s after that, after a preset select, after a dump | **none** worked, **none** answered |
| An unused id (0x26 on Chime) on its own, then a normal set | both answered, the normal set worked: an unused id is harmless |

- **Sending a set before the amp has answered the previous one makes the amp drop it
  and then ignore every later set** for the rest of the session. Only a new handshake
  brings sets back. Selects, dumps and knob events keep working meanwhile.
- The answer (the 29-byte message) arrives within about 0.05 s, so waiting for it costs
  almost nothing.
- Rules: **one set at a time, and wait for its answer before sending the next.** If no
  answer comes within about 1 s, sets are probably dead, and a new handshake is needed.
  A slider should send only its latest value once the previous set is answered, not
  every step.

### What the amp sends back after a set (confirmed, 2026-11-06)

**A set is not reported back.** The new value never shows up as a parameter report
(section 7): three Drive sets, all heard, gave no report at all
(`captures/seq_check.txt`). What the amp does send, every time:

1. at once, a 29-byte channel-0 message `(29, 0x0B, 0x01)` with the amp's next
   counter, for example `f000010c22054d000900000b00010000000400000000000000000000f7`
2. about 2 s later, a status message (45 bytes, `msg[11]` 0x07, `msg[13]` 0x03,
   `msg[26]` 0x7F), as after a preset-knob click

Neither message carries the value. To know a set's value, the Pi has to remember what
it sent, or read it from a dump (section 3).

### Preset select

A 29-byte message with one value byte:
`f000010c22054d0102 00 00 0b 00 0d 00 00 00 04 00 00 00 00 <value> 00 00 00 00 00 f7`
followed by the dump request (section 2), then further messages.

Values seen: `08` loaded "Jungle $lash" and `04` loaded "Chime 1: Class-A", so the value is
probably an index into the amp's preset list.

**The value is the preset-list index (confirmed 2026-11-06, `captures/check_amp_2.txt`):**
21, 60, 114, 124 and 127 each loaded the name the preset list (section 4) gives for that
index ("Angel P-Ball", "The Trooper", "AmbientAco", "User 1", "User 4"). **115 timed out**
(no dump within 4 s). On 2026-11-07 (`captures/amp_survey_2.txt`) 116 to 123 all loaded
the names the list gives, in about 0.4 s each, but **115 ("DirtyAcoBlues") timed out
again**. So all 128 except 115 load. Why 115 doesn't load isn't known.

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

This is the order of the handshake's preset list (section 4, "Preset list"), and 4 and 8
match the app captures. The list has 128 entries (0 to 127), so the amp has far more
presets than the knob's 16 positions. Selecting values above 20 has not been tried; the
list says 124 to 127 should be `User 1` to `User 4`.
Which value each knob position loads: see section 11.
A select sends no preset-change event; only the (29, 11, 1) message and the status
message came back besides the dump.

### Every control the app shows (confirmed 2026-11-07, `captures/windows/names.txt`)

Moving each control in the Line 6 app (Chime 1, then Gain/Drive on Jungle $lash),
decoded with `tools/pcap_to_text.py`. Key = block:sub (`msg[13]`, `msg[14]`), id
(`msg[17]`) and the id's namespace (`msg[18]`):

| App section | Control | Block:sub | Id / namespace | Values |
|---|---|---|---|---|
| Noise gate | Threshold | 5E:2 | 60 / 2 | 14 to 77 seen (the model says -96 to 0 dB) |
| Noise gate | Decay | 5E:2 | 0A / 0 | 0 to 1 |
| Volume pedal | Min | 04:3 | 09 / 3 | 0 to 1 |
| Volume pedal | Max | 04:3 | 0A / 3 | 0 to 1 |
| Amp | **Gain** (Gain models) | 2A:0 | 25 / 0 | 0 to 1 |
| Amp | **Drive** (Drive models) | 2A:0 | 26 / 0 | 0 to 1 |
| Amp | Bass / Mid / Treble / Presence | 2A:0 | 21 / 23 / 24 / 27, ns 0 | 0 to 1 |
| Amp | Volume | 74:3 | 24 / 3 | 0 to 1 |
| Compressor | Threshold | 23:3 | 63 / 2 | 0 to 1 |
| Compressor | Gain | 23:3 | 25 / 0 | 0 to 1 |
| EQ | Low, gain | 25:3 | 07 / 0, 73 / 2 | 0 to 1 |
| EQ | Low-mid, gain | 25:3 | 76 / 2, 79 / 2 | 0 to 1 |
| EQ | High-mid, gain | 25:3 | 7B / 2, 25 / 0 | 0 to 1 |
| EQ | High, gain | 25:3 | 7F / 2, 02 / 2 | 0 to 1 |
| Reverb (a spring model) | Time | 1F:3 | 0A / 0 | 0 to 1 |
| Reverb | Tone | 1F:3 | 46 / 2 | 0 to 1 |
| Reverb | Mix | 1F:3 | 7A / **1** | 0 to 1 |
| Panel | Reverb knob | 74:3 | 20 / 3 | 0 to 1 |

The EQ's order follows `fixed.models` (Low, gain, LMid, gain, HMid, Gain, Hi, gain).

What this changes:

- **The two "sub" bytes of a set can differ.** `msg[14]` is the block's sub and `msg[18]`
  the id's namespace. parameters.py has one `sub` for both, which is right for the amp
  (0/0) and the panel (3/3), but **not for "Reverb (mix)"**: the app sends block 1F
  **sub 3**, id 7A **namespace 1**; parameters.py sends sub 1 in both places, which is
  why it "changed nothing" (section 8 table). Live reports carry the namespace
  (`msg[27]`), so report keys `(block, id, namespace)` stay as they are.
- **Not every value is 0 to 1:** the gate threshold is sent as 14 to 77 (probably dB,
  negated). The value bytes are the float's top 16 bits as usual; only the range check in
  `encode_set_value` is in the way.
- **`msg[20]` ("unknown", section 8)** cycles 0, 1, 2, 3 in the app's sets. The Pi sends 1
  every time, which works.
- **The app paces sets like the Pi:** begin and set, then it waits for the 29-byte answer
  before the next (10 to 20 ms apart).

### The set message is four packed numbers (confirmed 2026-11-09, on the amp)

**A set's `msg[12:-1]` is 7-bit packed like a dump** (section 3: groups of 8 from
`msg[12]`, a byte of top bits first, MSB-first). Unpacked it is 21 bytes, four
little-endian 32-bit numbers and 5 zeros:

| Bytes | Number | Example (panel Volume) |
|---|---|---|
| 0-3 | block word: block, sub | `74 03 00 00` = 74:3 |
| 4-7 | **the parameter's symbol** (namespace << 8, id) | `24 03 00 00` = 0x324 |
| 8-11 | value type: 4 float, 3 on/off | `04 00 00 00` |
| 12-15 | the value: a float, or 1 / 0 | `5e 2f 17 3f` = 0.5906 |

All 3054 sets in the Windows captures repack byte for byte from this. What it explains:
- **"id" and "namespace" are one number, the symbol** (section 10's symbol table). The
  "namespace" is just its high byte: Volume 0x324 = id 24, namespace 3.
- **`msg[20]` ("unknown") is the top bits of the float's two low bytes.** The app sends
  the whole float, so it changes with the value; the Pi sends only the top 16 bits (the
  low two bytes 0, the `00 00 40` / `00 00 00` start of `encode_set_value`'s bytes is the
  same packing done by hand), which works. The Pi's `01` in `msg[20]` sets the top bit
  of the float's second-lowest byte, a change of about 1 part in 100,000: harmless, but
  it should be 0.
- **An id of 0x80 or more needs its top bit in `msg[12]`** (0x04: `msg[17]` is the 5th
  byte of that group). EQ Hi Shelf Gain is symbol **0x282**: the app sends `02 02` with
  `msg[12]` = 04 (names.txt), and the amp sets it. parameters.py had id 0x02, so the Pi
  sent symbol 0x202 and nothing moved; with 0x282 record 25:3/70 followed 0.1 and 0.9
  (2026-11-09). (An earlier note here said the app's set was broken: it isn't; that
  survey looked only from `msg[13]` on.)

**Dump records are the "...State" symbol** of the same name, low byte only: Lo Shelf Gain
is symbol 0x273, its state 0x26B, stored as record 6B in 25:3. With the `.models` files
(section 10: each model's params by `symbolicID`), every parameter's set symbol and dump
record can be found without a capture: symbol(name) and symbol(name + "State").

**Records the amp run found (2026-11-09, `captures/dump_params_2.txt`, `_3.txt`; same on
presets 4, 8, 0 and 14):**

| Parameter | Set symbol | Dump record |
|---|---|---|
| Gate Threshold / Decay | 5E:2 0x260 / 0x00A | 5F / 21 |
| Vol Min / Max | 04:3 0x309 / 0x30A | 06 / 07 |
| Comp Threshold / Gain | 23:3 0x263 / 0x025 | 62 / 1F |
| EQ Lo / LMid / HMid / Hi Freq | 25:3 0x007 / 0x276 / 0x27B / 0x27F | 6A / 6C / 6E / 6F |
| EQ Lo / LMid / HMid / Hi Gain | 25:3 0x273 / 0x279 / 0x025 / **0x282** | 6B / 6D / 1F / 70 |
| Reverb Time / Tone / Mix (spring) | 1F:3 0x00A / 0x246 / 0x17A | 21 / 45 / 75 |
| Gate / Wah / Comp / EQ / Vol / Reverb On | 74:3 | 38 / 3B / 3D / 3E / 3A / 34 |

**The "0x8000 flag" on switch records was ours, not the amp's** (found 2026-11-09): after
a set from the Pi a switch record read 0x8000 / 0x8001, because the Pi's `01` in
`msg[20]` is the top bit of the value's second byte, so "1" was sent as 0x8001. The same
set as four packed numbers stores a plain 1 (Reverb On: 32769 the old way, 1 packed). A
save made from such a dump stored the 0x8001 (User 1, 2026-11-09); the app's saves never
contain it.

**Packed sets checked on every parameter (2026-11-09, Chime 1):** all 37 settable
parameters, each set to two values, landed in the record in the table above, floats to
the last bit (0.2345 stored as 0.2345, where the old top-16-bits encoding gave 0.2344),
switches as plain 0 / 1, the gate threshold at 28.77 and 69.22, and EQ Hi Shelf Gain
(symbol 0x282, record 70). (Gain had no record because Chime 1 now has a Drive model.) A
save of a dump with no 0x8000s reloaded with none.

### Stages: on/off, types, order (2026-11-07, `captures/windows/session.txt`)

From a guided session (`tools/capture_gatherer.html`, log in `captures/windows/session_log.txt`).
The app shows the preset as a chain of stages: Gate, Wah, Stomp, a mod slot, Amp (with
the cab), Comp, EQ, Vol, Delay, Reverb. Each is one block in the dump (section 3).

**On/off (confirmed):** a normal set on the panel block, 74:3, namespace 3, with a whole
number: the first value byte (`msg[26]`) is `01` for on, `00` for off, the rest zero.
**`msg[22]` is `03` in these sets, not the `04` of every float set** (all on/off sets in
`session.txt` and `names.txt`), so it is probably the value's type. `build_set_message`
always sends `04`; whether the amp minds for on/off is untested.

| Stage | Gate | Wah | Stomp (FX1) | Mod (FX2) | Comp | EQ | Vol | Delay (FX3) | Reverb |
|---|---|---|---|---|---|---|---|---|---|
| 74:3 id | 4D | 51 | 48 | 47 | 4A | 4B | 49 | 46 | 50 |

The Amp and the cab have no switch (the app only moves between them).

**Which stages are on, and where they sit, differ per preset** (the session log notes 5
presets); the mod slot moved between "before Stomp", "after Stomp" and "after EQ". How
the order is stored isn't decoded yet; it's probably in the panel block (74:3).

**Changing a stage's type (seen 14 times):** no set, but an **upload to the edit buffer**
(see "Uploads" under the save command below): the header gives slot `FF FF FF FF` and
the data length, and the data is a short preset, 2 chunks:

1. the preset's first 210 bytes (the "PSRP" header and name; the same each time)
2. **just the changed block**: its info records (05 = the new model) and the model's
   records with their starting values

The number that "changed each time" in the header is the data length. All 14 rebuild
byte for byte (scratch `save4.py`, 2026-11-07).

The new models match the app (Fuzz Pi → Screamer, Phaser → U-Vibe, Brit Gain 18 →
Plexi 45, 4x12 Green 20s → Green 25s, Tube Echo → Multi-Head, Slap Plate → Vintage Plate),
and the records are the model's controls: Fuzz Pi has `33/0` DriveState, `1F/0`
GainState and `75/1` (the app calls them Drive, Gain, Tone). So: **to change a type,
upload the block with its new model and values to the edit buffer.** Not known yet:
whether the amp finds the block by its block number (most likely, since each stage
has its own) and what it does with records the new model doesn't have.

**The new type's knobs are normal sets in its block,** for example the wah's Position
(0C:3, id 6A, namespace 1) and Fuzz Pi's Drive (19:3, id 26/0), Gain (25/0) and Tone
(7A/1).

**Moving a stage (seen once):** a set on 74:3 id 40 (namespace 3), then a header message
and an upload of the panel block, then a 21-byte message `... 02 40 ...`. Not decoded.

**"Save as" (not seen):** the session's save-as uploaded the whole preset with slot 4
in its header, and then read back slot 4, so it went over Chime 1 like the first save.
Since the upload header carries the slot (below), save-as is very likely the same
upload with another slot number. Untested.

**Left for v1.1 (decided 2026-11-07 and 08):** type changes, stage moves, save-as, the
chain order, and tone export / import. v1.0 has every knob and on/off, reads each
stage's model (names from the Line 6 app's own files, loaded at start-up and never
committed, section 10), and saves to the current slot. Notes for v1.1:

- Tone export / import: first our own file (a dump's preset data, uploaded back to the
  edit buffer, slot FF FF FF FF; a whole preset there is untested), then Line 6's tone
  files (`.svl6p`, section 10; the app's Import / Export buttons, `exportDeviceTone` in
  APIV3EngineDLL.dll). They name each stage's model and knobs
  (`"amp": {"@model": "BritGainJ800", "Bass": 0.59, ...}`), so they convert to records
  through the symbol table and the `.models` files. One file exported from this amp
  would confirm the details. CustomTone (the Line 6 account's online sharing,
  `customtone/tones` etc.) is left out: it's Line 6's private web service and needs the
  user's login.

- The app only lets a stage go into certain chain positions (seen by the user when
  dragging). Find out why before writing moves: likely fixed regions (before the amp,
  after the amp, around the cab) or a stage-type rule. Capture several drags, including
  ones the app refuses, and compare the panel block before and after each.
- The type-change header is decoded (an upload to slot FF FF FF FF, below). What's left
  is trying one on the amp.
- Try save-as by uploading with another slot number, on a user preset; or capture the
  app saving into a different slot.

### Save command (one capture, 2026-11-07, `captures/windows/save.txt`)

**Saving uploads the whole preset to its slot.** Every upload in the captures (this
save, the session's save-as and 14 type changes) rebuilds byte for byte from the rules
below (scratch `save4.py`, 2026-11-07).

**Uploads.** All on channel 1 (`msg[7]` = 1):

1. **Header message**, counter N (`msg[8]`), index 0 (`msg[9]`). Its data (16 bytes) is
   four little-endian 32-bit numbers: `0C`, **length + 8**, **slot**, **length**. The slot
   is the preset number (4 for Chime 1), or `FF FF FF FF` for the edit buffer (a type
   change). "Length" is the data's length in bytes.
2. **Data messages**, all with counter N + 1, index 0, 1, 2..., each carrying the next
   **210 bytes** of the data (the last one less).
3. The amp answers once, after the last data message, with the usual 29-byte channel-1
   answer (`msg[11:14]` = `0B 00 01`).

**Every one of these messages** (and the dump's own chunks) uses the same framing:
`msg[10:12]` is the data length minus 1, split into two halves (`0D 01` = 0xD1 = 209 for
210 bytes, `0C 0A` = 202 for 203, `00 0F` = 15 for the header's 16, a dump's `0F 0F` =
255 for 256); the data is padded with zeros to a whole group of 7 and packed (section 3,
MSB-first); then `F7`.

**The data of a save is a preset in the dump's format**: "PSRP", the name, and the blocks
of records. A dump's unpacked data starts with its own 12-byte header,
`01 00 00 00`, a length, `00 00 00 00` (Chime: length 1297, the bytes after it), so the
preset is the dump's data after those 12 bytes. **Not proven: that the amp takes its own
dump back unchanged.** The app's upload is not a byte copy of the dump: it orders the
first records differently and leaves a few out (Chime: 1253 bytes uploaded, 1293 in the
dump read back straight after). Try it on a user preset first.

After saving, the app reads the preset back: a preset-list request (kind 0x0E, index 4),
a select of 4, and a dump request. The name stayed "Chime 1: Class-A".

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

### Losing and getting back the amp (2026-11-07, `captures/amp_survey_2.txt`)

| What happened | Noticed | Device back | New handshake |
|---|---|---|---|
| USB pulled while connected, then plugged back in | at once: `OSError(19, 'No such device')` from the read | at once, **same path** (`/dev/snd/midiC3D0`) | first try, 14.2 s, dump and all 128 names |
| Amp switched off while connected (USB left in), then on | about 1 s later, the same `OSError(19)` | 2.6 s after switching on, same path | first try, 13.3 s, dump OK, but **no preset names (0 of 128)** |

- The device path came back the same both times, but look it up again anyway
  (`find_device()`), because the card number can change.
- **Straight after power-on, the handshake gets the dump but no preset-list replies**,
  so the amp seems not to be ready for those yet. A reconnect should wait a few seconds
  after the device comes back, or check that the preset list isn't empty and ask again.
  How long to wait hasn't been measured.
- The USB-pull loss in `captures/check_amp.txt` (2026-11-06) took a few seconds to show
  up in the kernel; this time it was immediate. The time is set by Linux, not the code.

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
  area at byte `8 + 12*count`. **`defaultSymbolTable_Parker.bin` (910 symbols) is the
  Spider V MkII's:** symbol numbers are its model ids and its namespace-0 parameter ids
  (section 3, "Names: the amp's symbol table"). The other tables are for other products.

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
- **Numbering (confirmed 2026-11-07):** the knob's marking m comes out as position m,
  and marking 16 as position 0 (from the `% 16`).

### Position → name table (confirmed 2026-11-07, `captures/amp_survey_2.txt`)

Walked through markings 1 to 16, one click each, with the bounce rule and the refreshed
name from `AmpService`. Every click settled on the expected position.

| Marking | Pos | Preset | Marking | Pos | Preset |
|---|---|---|---|---|---|
| 1 | 1 | Chunk 2: Phat Chunk | 9 | 9 | Acoustic |
| 2 | 2 | Insane 1: Lunatic | 10 | 10 | Clean 1: US Double |
| 3 | 3 | Chime 1: Class-A | 11 | 11 | Clean 2: Jazz Chorus |
| 4 | 4 | Vibe 1: Auto Wah | 12 | 12 | Chime 1: Class-A |
| 5 | 5 | Vibe 2: Rotary | 13 | 13 | Chime 2: Echoes |
| 6 | 6 | Acoustic | 14 | 14 | Sugar Skull |
| 7 | 7 | Ambient 2: Glass | 15 | 15 | Crunch 2: Pasadena |
| 8 | 8 | Bass | 16 | 0 | Jungle $lash |

- Acoustic (6 and 9) and Chime 1 (3 and 12) appear twice. The old table below has the
  same repeats, so they're probably real, not errors.
- The old table is this one moved by one position (its position p+1 is position p here)
  for 8 to 15 and 0; its 2 to 7 were the bounce errors.
- Turning a knob near marking 11 sent a run of Drive (alt) reports (0.44 down to 0.0) on
  Clean 2. Probably a physical knob was touched; it shows that knob turns are reported
  live with the id the preset uses.

### Old position → name table (2026-10-30)

Recorded before the bounce was known, assuming one click per name announcement.
**Superseded** by the table above.

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

Answered on 2026-11-06: a dump after a set holds the new value (section 3); select
values 21 to 127 load the preset-list entry with the same index, except 115, which
timed out (section 8); panel-block sets (Volume, Reverb, FX) work (section 8); a set
does not show up in the live stream (section 8).

- The status message about 2 s after a set: does a knob-click handler mistake it for
  the end of a click? (It only settles when knob positions came first, so probably not.)
Answered on 2026-11-07: 116 to 123 load, 115 never does (section 8); the knob table
and numbering (section 11); FX2, FX3, their knobs and both Tone ids are in the dump
(section 3); what losing the amp looks like (section 9).

- Is there anything short of a new handshake that brings sets back after a set was sent
  too soon (section 8)? A select, a dump and waiting don't.
- How long after power-on until the handshake gets the preset list (section 9).
- Why preset 115 doesn't load.
- What the other dump blocks are (5E:2, 04:3, 0C:3, 19:3 to 1F:3, 21:3 to 25:3), and
  the amp block's records 0x1C and 0x1D (section 3).
- The cause of the wedge, and a reliable way to get the dump every time.
- Where the amp model and effect models are stored in the dump, and the layout of the
  rest of the dump (record numbering, Tone values).
- Whether the wire id always follows the symbol name (section 5).
- The Tone ids: which of 0x24 and 0x27 is Treble and which is Presence.
- (2A,02), and what the status message means exactly.
- msg[20] in set messages.
- The Save command.
- Why the long preset list stops at 114, why the short list has no reply for 0 and 34,
  and the 9 extra bytes in long-layout entries.
- Sets with sub other than 0 and 3, and FX2 / FX3 and their FX knobs (not tried).

## 13. Hardware notes

- Power the Pi from a proper 5 V 3 A supply. Earlier under-voltage caused reboots.
  Check with `vcgencmd get_throttled` (0x0 means fine).