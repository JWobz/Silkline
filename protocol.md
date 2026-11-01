# Spider V 20 MkII protocol notes

Working notes from reverse-engineering the amp over USB-MIDI. Status tags:
**confirmed** = tested on the amp, **inferred** = a guess that fits the data,
**unknown** = not understood yet.

## 1. Connection

- The amp is a class-compliant USB-MIDI device. On the Pi the raw device is
  `/dev/snd/midiC<N>D0`. `<N>` is the ALSA card number and it can change
  (it was 3, then different). `amidi -l` shows it as `hw:N,0,0`.
- Every message is SysEx: starts `F0`, ends `F7`.
- Line 6 header: `F0 00 01 0C 22 05 4D`, then two counter bytes (msg[7], msg[8]).
  The amp puts a periodic counter in msg[7..8] and a sequence number in replies.
- Messages are identified by their **shape**: `(length, msg[11], msg[13])`.

## 2. Handshake

- `handshake.txt` holds 258 messages. Send them one at a time and read the
  replies after each (about 260 replies in total).
- Replies contain the amp identity, the preset-name list, and a dump of the
  current preset.
- **Dump trigger (confirmed):** handshake line 8 (index 7) on its own makes the
  amp send the current-preset dump:
  `f000010c22054d010200000b000b0000000400003c007f7f7f7f0000f7`
- Dump = five 309-byte messages plus a final 29-byte message. The dump format is
  **not decoded**. Changing Drive min to max altered only 2 bytes (positions 276
  and 283 of the 4th 309-byte message).
- In the survey the dump sometimes came back as just a 29-byte ack, or arrived late
  in the next capture. Waiting for the final 29-byte chunk and retrying is still
  to do.

## 3. Messages from the amp

| Shape (len, msg[11], msg[13]) | Extra check              | Meaning                    | Status |
|-------------------------------|--------------------------|----------------------------|--------|
| (45, 0x07, 0x04)              |                          | parameter report           | confirmed |
| (45, 0x07, 0x03)              | msg[35] == 1, msg[26] != 0x7F | Save pressed          | confirmed |
| (45, 0x07, 0x03)              | msg[26] == 0x7F          | status                     | confirmed |
| (45, 0x07, 0x03)              | anything else            | heartbeat, about 1 per second | meaning unknown |
| (37, 0x0F, 0x05)              |                          | tap tempo                  | confirmed |
| 50 to 99 bytes, msg[13] == 1  |                          | preset info (name)         | confirmed |
| (29, 0x0B, 0x01)              |                          | periodic message with a counter in msg[8]; arrives by itself | ignore |
| 309 bytes, msg[13] == 1       |                          | dump chunk, **not** preset info | see section 2 |

### Parameter report (45 bytes)

- Address = `(msg[22], msg[26], msg[27])` = (block, id, sub).
- Value = 5 bytes at `msg[35:40]`.
- The same id in a different block is a different parameter (for example 0x24 is
  Volume in block 0x74 but a Tone part in block 0x2A; 0x46 is Reverb in one block
  and the FX3 button in another). Always use the full address as the key.

### Value decode (amp reports)

Value bytes `v0..v4`:

1. `flag = v1 & 0x20`
2. `third = v3`, with `0x80` added if the flag is set
3. `top = v4`
4. The float is `struct.unpack('<f', bytes([0, 0, third, top]))`

The result is 0.0 to 1.0 in 256 linear steps.

### Tap (37 bytes)

BPM = `decode_value(msg[26:31]) * 2` (confirmed by user tests, about 157 bpm in the
test case).

### Save (45 bytes)

Pressing the Save button gives shape `(45, 7, 3)` with `msg[35] == 1` and
`msg[26] != 0x7F` (confirmed).

### Heartbeat

Other `(45, 7, 3)` messages, once per second, with msg[26] wandering roughly 0 to 15.
It is not the preset position and strumming does not change it. **Unknown. Ignore it.**

### Preset info

- Name = printable ASCII of `msg[49:-1]`. Names are 7-bit packed, so every 8th
  byte is a 00 and is dropped by the printable filter.
- The amp announces the current preset about every 5 seconds and after any change.
- `msg[40]` is a "fingerprint" byte per preset. It is not unique and not an
  "edited" flag. **Unknown.**
- The amp never reports the knob position, only the preset name.

## 4. Parameter blocks

`msg[22]` selects the block.

| Block | Meaning |
|-------|---------|
| 0x74  | Panel: the physical controls |
| 0x2A  | Amp block (amp model dependent) |
| 0x19 / 0x1B / 0x1D | FX1 / FX2 / FX3 effect blocks (ids depend on the effect model in the preset) |
| 0x1F  | Reverb effect block |
| 0x6C  | Tap (hold) |

### Known parameters (block, id, sub)

| Address          | Name           | Notes |
|------------------|----------------|-------|
| (0x74, 0x24, 3)  | Volume         | physical knob |
| (0x74, 0x20, 3)  | Reverb         | physical knob |
| (0x74, 0x1A, 3)  | FX Knob (FX1)  | "Smart FX" knob when FX1 is on |
| (0x74, 0x1C, 3)  | FX Knob (FX2)  | when FX2 is on |
| (0x74, 0x1E, 3)  | FX Knob (FX3)  | when FX3 is on |
| (0x74, 0x48, 3)  | FX1 button     | colour suggests Stomp (inferred) |
| (0x74, 0x47, 3)  | FX2 button     | colour suggests Mod (inferred) |
| (0x74, 0x46, 3)  | FX3 button     | colour suggests Delay (inferred) |
| (0x2A, 0x25, 0)  | Drive          | |
| (0x2A, 0x24, 0)  | Tone (part)    | see caveat below |
| (0x6C, 0x72, 3)  | Tap (hold)     | |

### Caveats

- **Tone has no single id.** It moves several ids in block 0x2A (0x21, 0x23, 0x24,
  0x27 and others) and which ones depend on the amp model in the current preset.
  (0x2A, 0x02, 0) is not a float.
- The FX knob's panel id depends on which FX slot is switched on.
- The ids of the FX1/2/3 blocks depend on the effect model in the preset.
- In block 0x2A msg[23] is 0; elsewhere it is 3.

## 5. Preset knob positions

Assumes one click per announcement, one slow lap from 0 and back. Accepted as
"good for now". Positions 4/13, 5/12 and 1/15 repeat names, so some slots share a
preset.

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

"Chunk 2: Phat Chunk" was also seen once earlier.

## 6. Sending to the amp (from old PC-app captures, **not yet tested by sending**)

### Set a parameter: two messages

1. **Begin** (29 bytes):
   `HEADER(8 bytes, ends 00) SEQ 00 00 07 00 0A 00 00 00 10` + 10 zero bytes + `F7`
2. **Set** (37 bytes):
   `HEADER SEQ+1 00 00 0F 00 <block> 00 00 00 <id> 00 00 <msg[20]> 00 04 00 00 00`
   + 5 value bytes (msg[26:31]) + 5 zero bytes + `F7`
   - Block is at msg[15] (0x2A amp, 0x74 panel), id at msg[17].
   - msg[20] takes values 0 to 3 in the captures. **Unknown.** The Pi code sends 1.
   - The Pi code (`set_raw`, `begin_message`) uses a sequence counter that starts at
     0x0C and steps by 2.

### Value encoding for sets

Decoding the app's set messages with this rule gives a smooth 0 to 1 ramp
(518 samples, min 0.0, max 1.0, median step 1/256):

- `B2 = v3 | (0x80 if (v2 & 0x40) else 0)`
- `B3 = v4`
- `B0 = B1 = 0`. v0 and v1 look like junk or a counter.
- This differs from the amp-report layout, which uses v1 bit 5 instead.

Test vectors (set encoding):

| Raw 5 bytes  | Value    |
|--------------|----------|
| `5022405d3e` | about 0.4316 |
| `6033400c3e` | about 0.2734 |
| `7b1800023f` | about 0.5078 |

Panel sets in the Save_Preset capture use block 0x74, id 0x24 (Volume) with values
0.51 to 0.59, so the panel block appears to use the same encoding.

### Preset select

A 29-byte message with one value byte:
`f000010c22054d0102 00 00 0b 00 0d 00 00 00 04 00 00 00 00 <value> 00 00 00 00 00 f7`
followed by the dump request (section 2), then further messages (`...07 00 11...`,
a 21-byte `...03 00 09...`, `...07 00 10...`).

Values seen: `08` loaded "Jungle $lash" and `04` loaded "Chime 1: Class-A". These are
not the knob positions (1 and 4 or 13), so the value is probably an index into the
amp's own preset list. **Unconfirmed. Test values 0 to 15 on the amp.**

### Save command

**Not found.** The Save_Preset capture only contains panel-block Volume-style sets.
A new capture is needed.

## 7. Open questions

- Heartbeat meaning (msg[26] of the non-status `(45, 7, 3)` messages).
- Preset fingerprint byte (msg[40]).
- Dump format, and a reliable snapshot (wait for the final 29-byte chunk, retry).
- msg[20] in set messages.
- Preset-select value mapping, and the Save command.
- Whether the amp accepts sets in the panel block (Volume, Reverb, FX).
- Auto-detect the amp's ALSA card number.

## 8. Hardware notes

- Power the Pi from a proper 5 V 3 A supply. Earlier under-voltage caused reboots.
  Check with `vcgencmd get_throttled` (0x0 means fine).
