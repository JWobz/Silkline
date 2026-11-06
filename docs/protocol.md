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
- **A value is a 4-byte little-endian float**, after a 6-byte record header that starts
  with a record id. **The amp fills in the low bytes:** 0.5 is stored as `00 80 00 3f`
  (0.502), 0.75 as 0.752 and 1.0 as 1.0039. A set only carries the top 16 bits of the
  float (section 8), and the amp sets the next bit (half a step, about 0.002). Compare a
  dump to a sent value with a tolerance of about 0.005. The record **moves** between
  presets (by up to about 20 bytes), so a fixed offset doesn't work. **Record ids repeat**,
  though: every dump has `1f 00 00 00 03 00` 3 or 4 times (near 690-720, 1170-1190 and
  1265-1285, plus 1028 on Chime) and `33 …` up to twice. They are probably numbered per
  block (amp, effects, reverb), so a value has to be found by block and then id. The
  block layout isn't known yet.

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
- **The panel block is regular:** records 20 bytes apart, ids stepping by 2: FX knob 1
  0x26, FX1 0x28, FX knob 2 0x2A, FX2 0x2C, FX knob 3 0x2E, FX3 0x30, Reverb 0x32 (and
  Volume 0x3C further on). The FX on/off records have type byte 01, the knobs 03.

  "-" = the set changed nothing. Every value in the table reads back as set (MSB-first
  unpacking, both runs), at exactly one offset, except FX1 on preset 8: one byte changed
  there, but no float reads 0.5 then 0.75. FX1's header type byte is 01 instead of 03, so
  it may be an on/off value rather than a 0-to-1 float.
- Values found before any set, for the record (MSB-first): Drive on Chime 0.433 (the
  live report said 0.4316); Volume 0.592 / 0.240 / 0.702 / 0.700 and Reverb 0.204 /
  0.292 / 0.501 / 0.478 on presets 4 / 8 / 0 / 14; FX Knob (FX1) 1.0 and FX1 0.0 on all four.
- **Drive or Drive (alt) depends on the preset** (**confirmed** on 4 presets): Chime
  (preset 4) only responds to 0x25; Jungle $lash, Bass and Ambient 1 only respond to
  0x26. Probably it depends on the amp model. So "drive" has to send the one the current
  preset uses (or both).
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
- The dump's block layout: how to tell which `0x1F` / `0x33` record is the amp's Drive,
  and so which Drive id the current preset uses (section 3).
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