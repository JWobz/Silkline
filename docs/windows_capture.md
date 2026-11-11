# Capturing the Line 6 app on Windows

One session at the PC with the amp, about 30 minutes. It gives three things the API
still needs (protocol.md section 3 and section 8):

1. **Names:** which wire id each knob is (Bass, Mid, Treble, Gain or Drive, Presence, the
   FX controls). Seen in the app by name, so nothing is judged by ear.
2. **Amp models:** which model id in the dump goes with which amp model name.
3. **Save:** the message that saves a preset.

You record the amp's USB traffic with Wireshark while using the app, and write down
what you did, in order. Afterwards I decode the files.

## Before you start (once)

1. **Install Wireshark** from https://www.wireshark.org (Windows x64 installer). In the
   installer, **tick "Install USBPcap"**. That's the part that records USB. Restart the
   PC when it asks.
2. **Make a folder for the files:**
   `captures\windows` inside your copy of this repo.
3. **Open `notes.txt` in that folder** in Notepad. You'll write down each step as you do it.

## Setting up

1. **Unplug the amp's USB cable from the Pi, and plug it into the PC.** Only one of them
   can use the amp at a time.
2. **Open the Spider V Remote app** and let it connect to the amp. Leave the app's
   window where you can see it.
3. **Open Wireshark.** On its start page there are interfaces called `USBPcap1`,
   `USBPcap2` and so on. To find the amp's:
   - Double-click `USBPcap1` to start recording, move any slider in the app, and watch:
     if lines scroll in, that's the one. If not, stop (red square), and try `USBPcap2`.
   - Once you've found it, stop and close that recording without saving.
4. Each part below is **its own recording**: start it (double-click the interface), do
   the steps, stop it (red square), then **File > Save As**, into the `captures\windows`
   folder, with the name given (keep the `.pcapng` type).

**Go slowly:** about **5 seconds between actions**, so each one is easy to tell apart.
Write each one in `notes.txt` as you do it.

## Part 1: names (save as `names.pcapng`)

1. In the app, **pick preset "Chime 1: Class-A"** and wait 5 s.
2. Start recording.
3. For **each amp knob the app shows** (Bass, Mid, Treble, Gain or Drive, Presence),
   in that order:
   - drag it **all the way up**, wait 5 s
   - drag it **all the way down**, wait 5 s
   - write the knob's name in `notes.txt`, exactly as the app shows it
4. Then the same for **Volume** and **Reverb**.
5. Then the **effects**: for each of the three FX slots, switch it **on**, wait 5 s,
   **off**, wait 5 s; and if the app shows a mix or amount knob for it, drag that up,
   then down. Note each one with its name.
6. **Pick preset "Jungle $lash"**, wait 5 s, and do the **Gain or Drive** knob again (it
   may have the other name there). Note it.
7. Stop, and save as `names.pcapng`.

## Part 2: amp models (save as `models.pcapng`)

1. Start recording.
2. Pick these presets one at a time in the app. For each, wait 5 s, then write down
   **the preset name and the amp model name the app shows** (and the effect names, if
   it shows them):
   - Chime 1: Class-A
   - Jungle $lash
   - Bass
   - Acoustic
   - Clean 1: US Double
   - Clean 2: Jazz Chorus
   - Crunch 2: Pasadena
   - Chunk 2: Phat Chunk
   - Insane 1: Lunatic
   - Vibe 1: Auto Wah
   - Ambient 1: Black Hole
3. Stop, and save as `models.pcapng`.

## Part 3: saving (save as `save.pcapng`)

This **overwrites one preset on the amp**. Use **User 4**, the last user slot.
Anything stored there will be replaced.

1. Pick **Chime 1: Class-A**, and turn its **Volume** to about halfway, so there's
   a change to save.
2. Start recording.
3. In the app, **save the preset to User 4**. If it lets you name it, call it
   **`PiTest`**; the name makes the message easy to find. Note exactly what you clicked.
4. Wait 5 s. Then **pick User 4** in the app, and check it says PiTest. Note that too.
5. Stop, and save as `save.pcapng`.

## Afterwards

1. **Close the app**, unplug the amp from the PC, and **plug it back into the Pi**.
   Power-cycle the amp if anything seems stuck (protocol.md section 9).
2. Copy the `captures\windows` folder to the Pi, or just tell me it's done; I can copy it.
3. Don't send or share the `.pcapng` files elsewhere. They only hold USB traffic to the
   amp, but keep them with the project like the other captures.

## If something goes wrong

- **No `USBPcap` interfaces in Wireshark:** USBPcap wasn't installed, or the PC wasn't
  restarted. Run the Wireshark installer again with "Install USBPcap" ticked.
- **The app won't connect:** close Wireshark, reconnect the app, then start Wireshark.
- **You lose track mid-part:** stop, save what you have with `_1` added to the name,
  note where you stopped, and start that part again.
