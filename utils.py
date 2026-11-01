SPIDER_KEYWORD = "spider"

def find_amp_port():
        """ Finds the amp's raw MIDI device by looking for it in the ALSA card list. """
        card = None
        with open("/proc/asound/cards") as f:
            for line in f:
                first = line.split()[0] if line.split() else ""
                if first.isdigit():
                    card = first          # a card's first line: remember its number
                if SPIDER_KEYWORD in line.lower() and card is not None:
                    return f"/dev/snd/midiC{card}D0"
        raise RuntimeError("Could not find amp port. Please check that the amp is connected and powered on.")