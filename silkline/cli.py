"""
cli.py

The silkline command: a prompt for using the amp from a terminal (README).

main() connects straight away (logging each try, retrying until the amp is
there), then runs Shell until exit. Shell is a cmd.Cmd: each do_<name> method is
a command, and its docstring is what "help <name>" prints. It only uses
AmpService's public API, so a test can give it a fake service.
"""

import cmd
import difflib
import readline
import shutil
import threading
import time

import silkline
from silkline import AmpService, ConnectionState, EventType, style
from silkline.errors import AmpError
from silkline.logger import Logger
from silkline.protocol.parameters import PARAMETERS

class UsageError(ValueError):
    """A command typed without what it needs: shown as a quiet hint, not an error."""

STATE_COLOURS = {ConnectionState.CONNECTED: style.good,
                 ConnectionState.CONNECTING: style.busy,
                 ConnectionState.DISCONNECTED: style.bad}


class Shell(cmd.Cmd):
    """The silkline> prompt, on a connected AmpService."""

    prompt = "silkline> "

    def __init__(self, service):
        super().__init__()
        self.watching = False
        self.prompt = style.prompt_paint(style.ACCENT, "silkline") + style.prompt_paint(style.DIM, "> ")
        self.service = service
        service.on_change(self._show_change)

    def _say(self, text):
        """Print a line from the reader thread over the prompt, then redraw the prompt
        and whatever was half typed (readline's buffer) underneath."""
        print(
            f"\r{text}\n{self.prompt}{readline.get_line_buffer()}", end="", flush=True
        )

    def _complete(self, names, line, begidx, endidx):
        """Tab-completion for names with spaces and dashes.

        readline only hands over the last word (from begidx), so this matches on
        everything typed after the command and returns the rest of each name from
        where that word starts. "get eq lo" + Tab: typed "eq lo", the word starts 3
        in, so "EQ Low Gain" gives "Low Gain"."""
        start = line.index(" ") + 1
        typed = line[start:endidx].lower()
        return [n[begidx - start :] for n in names if n.lower().startswith(typed)]

    def complete_get(self, text, line, begidx, endidx):
        """Tab after get, set and params: parameter names."""
        return self._complete([p.name for p in PARAMETERS], line, begidx, endidx)

    def complete_set(self, text, line, begidx, endidx):
        return self._complete([p.name for p in PARAMETERS], line, begidx, endidx)

    def complete_params(self, text, line, begidx, endidx):
        return self._complete([p.name for p in PARAMETERS], line, begidx, endidx)

    def complete_preset(self, text, line, begidx, endidx):
        """Tab after preset: preset names."""
        return self._complete(self.service.presets().values(), line, begidx, endidx)

    def get_names(self):
        """The method names cmd looks through, without do_EOF, so help and
        did-you-mean don't list it. Ctrl-D still works."""
        return [n for n in super().get_names() if n != "do_EOF"]

    def default(self, line):
        """An unknown command: suggest the closest one (difflib), or point at help."""
        word = line.split()[0]
        commands = [n[3:] for n in self.get_names() if n.startswith("do_")]
        close = difflib.get_close_matches(word, commands, n=1)
        if close:
            print(f"unknown command, {word}:" + style.dim(f"did you mean {close[0]}"))
        else:
            print(f"unknown command {word}: type help")

    def emptyline(self):
        """An empty line does nothing (cmd would repeat the last command)."""
        pass

    def onecmd(self, line):
        """Run one command; a bad value or an amp error is printed, not a crash."""
        try:
            return super().onecmd(line)
        except UsageError as e:
            print(style.dim(f"  {e}"))
        except (ValueError, AmpError) as e:
            print(style.bad(f"{style.BAD_MARK} {e}"))

    def do_exit(self, arg):
        """exit
        Disconnect from the amp and leave. (Ctrl-D and Ctrl-C work too.)"""
        return True

    def do_quit(self, arg):
        """quit
        The same as exit."""
        return True

    def do_EOF(self, arg):
        """Ctrl-D: leave, like exit."""
        print()
        return True

    def do_status(self, arg):
        """status
        Show the connection, the loaded preset (name, number, knob position) and
        the tap tempo. "-" means not known yet (the number after a knob move)."""
        state = self.service.state()
        number, name, knob_pos = (
            state.preset_number,
            state.preset_name,
            state.knob_position,
        )
        bpm = state.bpm

        if name is None:
            name = "not known"
        if knob_pos is None:
            knob_pos = "-"
        if bpm is None:
            bpm = "-"

        if number is None:
            shown = f"{name} " + style.dim("(slot not known: load it with preset)")
        else:
            shown = style.dim(f"#{number}") + f" {name}"
        

        print(" " + style.label("connection") + STATE_COLOURS[state.connection](state.connection.value))
        print(" " + style.label("preset") + shown)
        print(" " + style.label("knob") + str(knob_pos))
        print(" " + style.label("tempo") + (f"{bpm} bpm" if bpm != "-" else "-")) 

    def do_preset(self, arg):
        """preset <number or name>
        Load a preset: "preset 8", or part of its name, any case: "preset jungle".
        If the name matches more than one, they are listed and none is loaded.
        Nothing is saved on the amp."""
        if not arg:
            raise UsageError("usage: preset <number or name>")
        elif arg.isdigit():
            n = int(arg)
            name = self.service.select_preset(n)
            print(style.good(f"{style.OK_MARK} loaded") + f" {style.dim('#' + str(n))} {name}")
        else:
            matches = []
            for number, preset in self.service.presets().items():
                if arg.lower() in preset.lower():
                    matches.append((number, preset))
            if len(matches) == 0:
                print(f"no preset called {arg!r}")
            else:
                if len(matches) == 1:
                    print(f"Found preset {matches[0][0]} {matches[0][1]}")
                    n = matches[0][0]
                    name = self.service.select_preset(n)
                    print(style.good(f"{style.OK_MARK} loaded") + f" {style.dim('#' + str(n))} {name}")
                else:
                    preset_string = "Found multiple presets: \n"
                    for match in matches:
                        preset_string += f"{match[0]} {match[1]}\n"
                    print(preset_string)

    def do_presets(self, arg):
        """presets [text]
        List the presets with their numbers. With text, only names that
        contain it, any case: "presets chime"."""
        given_preset = arg.lower() if arg else None
        presets = sorted(self.service.presets().items())    
        if given_preset:
            presets = [(n, name) for n, name in presets if given_preset in name.lower()]
        if not presets:
            print(style.dim("  no presets match"))
            return
        current = self.service.state().preset_number
        width = max(len(name) for _, name in presets) + 10
        columns = max(1, shutil.get_terminal_size().columns // width)
        rows = -(-len(presets) // columns)
        for r in range(rows):
            line = ""
            for c in range(columns):
                i = c * rows + r
                if i < len(presets):
                    n, name = presets[i]
                    if n == current:
                        line += style.accent(f"{style.HERE_MARK} #{n:<4} {name}".ljust(width))
                    else:
                        line += "  " + style.dim(f"#{n:<4}") + f" {name}".ljust(width - 7)
                
            print(line)

    def do_preset_knob(self, arg):
        """preset_knob
        The 16 presets on the amp's preset knob, by marking (1 to 16), with their
        slot numbers; "▶" marks where the knob is now. Marking m loads slot
        (m + 8) % 16, so saving into slots 0 to 15 changes what the knob loads.
        Names are from the connect (a rename in the app shows after a reconnect)."""
        presets = self.service.presets()
        position = self.service.state().knob_position
        for marking in range(1, 17):
            slot = (marking + 8) % 16
            name = presets.get(slot, "?")
            row = f"{marking:>2}  #{slot:<3} {name}"
            if marking % 16 == position:
                print(style.accent(f" {style.HERE_MARK} {row}"))
            else:
                print("   " + f"{marking:>2}  " + style.dim(f"#{slot:<3}") + f" {name}")

    def do_get(self, arg):
        """get <name>
        Show one parameter's value: "get bass", "get eq low gain". Names are any
        case; "params" lists them. Most are 0 to 1; switches are 0 (off) or 1 (on)."""
        if not arg:
            raise UsageError("usage: get <name>")
        value = self.service.get(arg)
        if value is None:
            print(f"{arg} not known yet")
        else:
            print(f"{arg}: {value:.2f}")

    def do_set(self, arg):
        """set <name> <value>
        Change a parameter on the amp: "set bass 0.3", "set eq low-mid gain 0.7".
        The value is the last word. Most are 0 to 1 (Gate Threshold is 14 to 77).
        Nothing is saved until "save"."""
        name, _, text = arg.rpartition(" ")
        if not name:
            raise UsageError("usage: set <name> <value>")
        self.service.set(name, float(text))
        print(f"{name}: {float(text)}")

    def do_on(self, arg):
        """on <stage>
        Turn a stage on: "on reverb" (the same as "set reverb on 1"). Stages: gate,
        vol, wah, stomp, mod, delay, reverb, comp, eq."""
        self._switch(arg, 1)

    def do_off(self, arg):
        """off <stage>
        Turn a stage off: "off delay". See "help on"."""
        self._switch(arg, 0)

    def do_params(self, arg):
        """params [text]
        List the parameters and their values ("-" is not known yet). With text, only
        names that contain it, any case: "params eq". Gain and Drive are the same
        knob, so they show the same value."""
        given_param = arg.lower() if arg else None
        param_string = "Parameters: \n"
        for param in PARAMETERS:
            if param.record is None: 
                continue
            if given_param is None or given_param in param.name.lower():
                value = self.service.get(param.name)
                if value is None:
                    shown = style.dim("-")
                elif param.kind == "switch":
                    shown = style.good("on") if value else style.dim("off")
                else:
                    fraction = (value - param.low) / (param.high - param.low)
                    shown = style.meter(fraction) + f" {value:.2f}"
                param_string += " " + style.label(param.name) + shown + "\n"
        bpm = self.service.state().bpm
        param_string += " " + style.label("Tempo") + (f"{bpm} bpm" if bpm else style.dim("-")) + "\n"
        print(param_string)

    def do_models(self, arg):
        """models
        Show each stage's model in the loaded preset. Names need the Line 6 app's
        files in ~/.config/silkline/app_data (README); without them it shows ids
        or numbers."""
        models = self.service.state().models
        if not models:
            print("No models yet")
            return
        for stage, model in models.items():
            shown = model["name"] or model["id"] or model["number"]
            print(f"{stage:<8} {shown}")

    def do_save(self, arg):
        """save
        Overwrite the loaded preset on the amp with how it is now (every set
        included). Asks first; only "y" saves. It can't be undone. Load the preset
        with "preset" first: after a knob move the amp doesn't say which slot it is."""
        state = self.service.state()
        number, name = state.preset_number, state.preset_name
        if number is None:
            raise ValueError(
                "load a preset with 'preset' first: the amp doesn't say which slot is loaded"
            )
        answer = input(f'Overwrite preset {number} "{name}" on the amp? (y/n) ')
        if answer.strip().lower() != "y":
            print("Not saved")
            return
        print(style.busy(f"{style.BUSY_MARK} saving…"))
        name = self.service.save()
        print(style.good(f"{style.OK_MARK} saved") + f" {style.dim('#' + str(number))} {name}")

    def do_watch(self, arg):
        """watch on | off
        Show changes made on the amp as they happen: knob turns, the preset knob,
        the tap button. They print over the prompt; you can still type."""
        if arg == "on":
            print("watching, turn a knob")
            self.watching = True
        elif arg == "off":
            self.watching = False
        else:
            raise UsageError("usage: watch <on> / <off>")

    def do_log(self, arg):
        """log on | off
        Show or hide the library's log lines (connecting, retries, warnings).
        Connection and preset changes are always shown."""
        if arg == "on":
            Logger.enabled = True
        elif arg == "off":
            Logger.enabled = False
        else:
            raise UsageError("usage: log <on>/<off>")

    def _switch(self, arg, value):
        """on / off: set a switch, adding " on" to the name if it isn't there."""
        if not arg:
            raise UsageError("usage: on <name> / off <name>")
        name = arg if arg.lower().endswith(" on") else arg + " on"
        self.service.set(name, value)
        print(f"{name} " + (style.good("on") if value else style.dim("off")))

    def _show_change(self, event):
        """While watching: print knob turns, preset-knob clicks and taps (reader thread)."""
        if not self.watching:
            return
        if event.event_type == EventType.PARAMETER_CHANGED:
            name = event.data["name"] or event.data["key"]
            self._say(f"{name} = {event.data['value']:.2f}")
        elif event.event_type == EventType.KNOB_MOVED:
            self._say(f"knob: {event.data['position']}")
        elif event.event_type == EventType.TAP:
            self._say(f"tap: {event.data['bpm']} bpm")


def main():
    """The silkline command: connect, log what happens, then run the prompt.

    Connection changes and preset changes are printed as they happen, from the
    service's reader thread. The prompt appears once the amp is connected; Ctrl-C
    while waiting leaves. The amp is always disconnected at the end.
    """
    print(style.banner(silkline.__version__))
    service = AmpService()
    connected = threading.Event()

    def show(event):
        now = time.strftime("%H:%M:%S")
        if event.event_type == EventType.CONNECTION_CHANGED:
            state = event.data["state"]
            print(f"{style.dim(now)} {STATE_COLOURS[state](state.value)}")
            error = event.data.get("error")
            if error:
                print(error)
            if state == ConnectionState.CONNECTED:
                connected.set()
        elif event.event_type == EventType.PRESET_CHANGED:
            number = event.data["number"]
            tag = style.dim(f"#{number}") + " " if number is not None else ""
            print(f"{style.dim(now)} {tag}{event.data['name']}")

    service.on_change(show)
    service.keep_connected()
    try:
        connected.wait()
        Logger.enabled = False
        print(
            'connected. log lines hidden: "log on" shows them. "help" lists the commands.'
        )
        Shell(service).cmdloop()
    except KeyboardInterrupt:
        print()
    finally:
        service.stop()
