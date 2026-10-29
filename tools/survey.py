import os
import select
import sys

from amp import Amp

DUMP_REQUEST = bytes.fromhex("f000010c22054d010200000b000b0000000400003c007f7f7f7f0000f7")
OUT_DIR = "captures/survey"

POSITIONS = (("min", "fully down"), ("mid", "to 12 o'clock"), ("max", "fully up"))

def build_steps():
    steps = [("baseline", 
               "Set the Drive, Tone, Volume, Reverb and FX knob to 12 o'clock."
               "Turn all three FX buttons OFF. Then don't touch anything else.",)]
    for knob in ("drive", "tone", "volume", "reverb"):
        for pos, text in POSITIONS:
            steps.append((f"{knob}_{pos}", f"Turn {knob.title()} {text}."))
        steps.append((f"baseline_after_{knob}", f"Put {knob.title()} back to 12 o'clock."))
    for n in (1, 2, 3):
        steps.append((f"fx{n}_on", f"Turn ONLY FX{n} on (the others off)."))
    steps.append(("fx_all_off", "Turn all three FX buttons off."))
    for n in (1, 2, 3):
        for pos, text in POSITIONS:
            if pos == "min":
                instruction = f"Turn ONLY FX{n} on (the others off). Then turn the FX{n} knob {text}."
            else:
                instruction = f"Turn the FX knob {text}."
            steps.append((f"fxknob_fx{n}_{pos}", instruction))
    steps.append(("final_baseline", "Turn all FX off and put the FX knob at 12 o'clock."))
    return steps

def wait_for_enter(amp):
    live = []
    while True:
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        if ready:
            sys.stdin.readline()
            return live
        live.extend(amp.read_messages(quiet=0.05, limit=0.2))

def snapshot(amp):
    amp.send(DUMP_REQUEST)
    return amp.read_messages()

def save_lines(path, messages):
    with open(path, "w") as f:
        for msg in messages:
            f.write(msg.hex() + "\n")

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    amp = Amp()
    try:
        amp.handshake()
        for label, instruction in build_steps():
            dump_path = f"{OUT_DIR}/{label}.dump.txt"
            if os.path.exists(dump_path):
                print(f"Skipping {label} (already exists)")
                continue
            print(f"\n[{label}] {instruction}")
            print("Press Enter when it is set.")
            live = wait_for_enter(amp)
            dump = snapshot(amp)
            sizes = [len(m) for m in dump]
            if sizes.count(309) != 5:
                print(f"  warning: unexpected reply sizes {sizes}")
            save_lines(f"{OUT_DIR}/{label}.live.txt", live)
            save_lines(dump_path, dump)
            print(f"  saved: {len(live)} live reports, {len(dump)} dump messages")    
    except KeyboardInterrupt:
            print("\nStopping")
    finally:
        amp.close()

if __name__ == "__main__":
    main()