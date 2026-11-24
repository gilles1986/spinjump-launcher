"""SMW Play Launcher: set it up once, then "Play" on a website starts the hack directly.

Without an argument the setup window opens. With an address (smwplay://play?url=…) it downloads,
patches and starts the hack in the emulator.
"""
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import core


def run_play(link: str) -> int:
    try:
        req = core.parse_url(link)
    except core.LauncherError as e:
        messagebox.showerror("SMW Play Launcher", str(e))
        return 1
    cfg = core.load_config()
    if core.missing_settings(cfg):
        messagebox.showinfo("SMW Play Launcher", "The launcher is not set up yet. It only takes a minute.")
        run_setup(pending=link)
        return 0

    if not core.host_trusted(req["host"]):
        messagebox.showerror(
            "SMW Play Launcher",
            f"{req['host']} is not on the list of trusted sites. For security reasons the launcher only downloads "
            "from those sites. Site owners can contact Spinjump to be added.",
        )
        return 1

    root = tk.Tk()
    root.title("SMW Play Launcher")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=16)
    frame.pack()
    ttk.Label(frame, text=req["title"] or req["id"] or req["host"], font=("Segoe UI", 11, "bold")).pack(anchor="w")
    status = tk.StringVar(value="Starting …")
    ttk.Label(frame, textvariable=status, width=44).pack(anchor="w", pady=(6, 8))
    bar = ttk.Progressbar(frame, length=320, maximum=1.0)
    bar.pack()
    events: "queue.Queue" = queue.Queue()
    pick_ready = threading.Event()
    pick_box = {}
    fx_ready = threading.Event()
    fx_box = {}

    def choose(names, last=None):  # runs in the worker thread, the dialog in the main thread
        events.put(("choose", (names, last)))
        pick_ready.wait()
        return pick_box.get("v")

    def work():
        try:
            rom = core.prepare(
                cfg, req, lambda s: events.put(("status", s)), lambda p: events.put(("progress", p)), choose
            )
            while True:
                try:
                    core.launch(cfg, rom, lambda s: events.put(("status", s)), lambda p: events.put(("progress", p)))
                    break
                except core.FxpakUnavailable as e:
                    # No silent fallback: ask first, then (if wanted) switch permanently.
                    events.put(("fxpak_down", str(e)))
                    fx_ready.wait()
                    fx_ready.clear()
                    answer = fx_box.get("v")
                    if answer == "retry":
                        continue
                    if answer == "emulator":
                        core.switch_to_emulator(cfg)
                        continue
                    events.put(("done", None))
                    return
            events.put(("done", None))
        except core.LauncherError as e:
            events.put(("error", str(e)))
        except Exception as e:  # nie still scheitern
            events.put(("error", f"Unexpected error: {e}"))

    def poll():
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == "status":
                    status.set(value)
                elif kind == "progress":
                    bar["value"] = value
                elif kind == "choose":
                    names, last = value
                    top = tk.Toplevel(root)
                    top.title("Which patch should start?")
                    top.transient(root)
                    pf = ttk.Frame(top, padding=16)
                    pf.pack()
                    ttk.Label(pf, text="All patches in the ZIP are ready. Which one should start?").pack(anchor="w")
                    box = tk.Listbox(pf, width=60, height=min(10, len(names)), exportselection=False)
                    for n in names:
                        box.insert("end", n)
                    box.selection_set(names.index(last) if last in names else 0)
                    box.pack(pady=8)

                    def ok(box=box, top=top, names=names):
                        sel = box.curselection()
                        pick_box["v"] = names[sel[0]] if sel else None
                        top.destroy()
                        pick_ready.set()

                    ttk.Button(pf, text="Start", command=ok).pack(anchor="e")
                    box.bind("<Double-Button-1>", lambda _e, ok=ok: ok())
                    top.protocol("WM_DELETE_WINDOW", ok)
                elif kind == "fxpak_down":
                    top = tk.Toplevel(root)
                    top.title("FXPak Pro not reachable")
                    top.transient(root)
                    pf = ttk.Frame(top, padding=16)
                    pf.pack()
                    ttk.Label(pf, text=value, wraplength=420, justify="left").pack(anchor="w", pady=(0, 12))
                    ttk.Label(
                        pf,
                        text="Start QUsb2Snes or connect the FXPak and try again, or switch to the emulator permanently "
                        "(you can undo this in the setup window).",
                        wraplength=420,
                        justify="left",
                        foreground="#666",
                    ).pack(anchor="w", pady=(0, 12))
                    btns = ttk.Frame(pf)
                    btns.pack(anchor="e")

                    def answer(v, top=top):
                        fx_box["v"] = v
                        top.destroy()
                        fx_ready.set()

                    ttk.Button(btns, text="Cancel", command=lambda: answer(None)).pack(side="left", padx=4)
                    ttk.Button(btns, text="Switch to emulator", command=lambda: answer("emulator")).pack(side="left", padx=4)
                    ttk.Button(btns, text="Try again", command=lambda: answer("retry")).pack(side="left", padx=4)
                    top.protocol("WM_DELETE_WINDOW", lambda: answer(None))
                elif kind == "done":
                    root.after(600, root.destroy)
                    return
                elif kind == "error":
                    messagebox.showerror("SMW Play Launcher", value, parent=root)
                    root.destroy()
                    return
        except queue.Empty:
            pass
        root.after(80, poll)

    threading.Thread(target=work, daemon=True).start()
    poll()
    root.mainloop()
    return 0


def link_generator(parent) -> None:
    """Small tool for site owners and the curious: patch address in, protocol link out."""
    top = tk.Toplevel(parent)
    top.title("Link generator")
    f = ttk.Frame(top, padding=16)
    f.pack(fill="both", expand=True)
    f.columnconfigure(1, weight=1)
    fields = {}
    for r, (key, label) in enumerate(
        [("url", "Address of the .bps or .zip"), ("id", "ID (optional)"), ("title", "Title (optional)"), ("sha256", "SHA-256 (optional)")]
    ):
        ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 10))
        fields[key] = tk.StringVar()
        ttk.Entry(f, textvariable=fields[key], width=64).grid(row=r, column=1, sticky="ew")
    out = tk.StringVar()
    note = tk.StringVar()
    ttk.Entry(f, textvariable=out, state="readonly", width=64).grid(row=5, column=1, sticky="ew", pady=(12, 0))
    ttk.Label(f, text="Link").grid(row=5, column=0, sticky="w", pady=(12, 0))
    ttk.Label(f, textvariable=note, foreground="#666", wraplength=520, justify="left").grid(
        row=6, column=1, sticky="w", pady=4
    )

    def make(*_):
        try:
            link = core.build_link(*(fields[k].get() for k in ("url", "id", "title", "sha256")))
        except core.LauncherError as e:
            out.set("")
            note.set(str(e) if fields["url"].get().strip() else "")
            return
        out.set(link)
        host = core.check_download_url(fields["url"].get().strip())
        note.set(
            "" if core.host_trusted(host)
            else f"{host} is not on the list of trusted sites. The launcher rejects this link."
        )

    for v in fields.values():
        v.trace_add("write", make)

    def copy():
        if out.get():
            top.clipboard_clear()
            top.clipboard_append(out.get())
            note.set("Copied.")

    ttk.Button(f, text="Copy", command=copy).grid(row=7, column=1, sticky="e")


def run_setup(pending=None) -> None:
    cfg = core.load_config()
    root = tk.Tk()
    root.title("SMW Play Launcher: Setup")
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    vars_ = {k: tk.StringVar(value=cfg[k]) for k in core.DEFAULTS}

    def row(r, label, key, kind=None, hint=None, parent=None):
        parent = parent or frame
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 10))
        ttk.Entry(parent, textvariable=vars_[key], width=56).grid(row=r, column=1, sticky="ew")
        if kind:
            def browse():
                if kind == "dir":
                    p = filedialog.askdirectory(parent=root)
                elif kind == "rom":
                    p = filedialog.askopenfilename(parent=root, filetypes=[("SNES ROM", "*.sfc *.smc"), ("All files", "*.*")])
                else:
                    p = filedialog.askopenfilename(parent=root, filetypes=[("Program", "*.exe"), ("All files", "*.*")] if sys.platform == "win32" else [("All files", "*")])
                if p:
                    vars_[key].set(p.replace("/", "\\") if sys.platform == "win32" else p)

            ttk.Button(parent, text="Browse …", command=browse).grid(row=r, column=2, padx=(8, 0))
        if hint:
            ttk.Label(parent, text=hint, foreground="#666").grid(row=r + 1, column=1, sticky="w")

    row(0, "Super Mario World ROM", "rom_path", "rom", "Your own, unmodified ROM. No ROMs are hosted.")
    row(2, "Hacks folder", "hacks_dir", "dir", "Patched hacks are saved here.")

    ttk.Label(frame, text="Play on").grid(row=4, column=0, sticky="w", pady=4, padx=(0, 10))
    radios = ttk.Frame(frame)
    radios.grid(row=4, column=1, sticky="w")
    ttk.Radiobutton(radios, text="Emulator", variable=vars_["target"], value="emulator").pack(side="left", padx=(0, 16))
    ttk.Radiobutton(radios, text="FXPak Pro (via QUsb2Snes)", variable=vars_["target"], value="fxpak").pack(side="left")

    emu = ttk.Frame(frame)
    emu.columnconfigure(1, weight=1)
    row(0, "Emulator", "emulator_path", "exe", parent=emu)
    row(2, "Emulator arguments", "emulator_args", None, parent=emu)
    hint = tk.StringVar()
    ttk.Label(emu, textvariable=hint, foreground="#666", wraplength=520, justify="left").grid(row=3, column=1, sticky="w")

    fx = ttk.Frame(frame)
    fx.columnconfigure(1, weight=1)
    row(0, "QUsb2Snes address", "fxpak_host", None, parent=fx)
    row(1, "Port", "fxpak_port", None, parent=fx)
    row(2, "Device", "fxpak_device", None, "Empty = first device found.", parent=fx)
    row(4, "Folder on the SD card", "fxpak_folder", None, "QUsb2Snes must be running and the FXPak connected.", parent=fx)

    def show_target(*_):
        if vars_["target"].get() == "fxpak":
            emu.grid_remove()
            fx.grid(row=5, column=0, columnspan=3, sticky="ew")
        else:
            fx.grid_remove()
            emu.grid(row=5, column=0, columnspan=3, sticky="ew")

    def update_hint(*_):
        path = vars_["emulator_path"].get().strip()
        name = core.detect_emulator(path)
        if not path:
            hint.set("Leave empty: Windows opens the ROM with the default program.")
        elif vars_["emulator_args"].get().strip():
            hint.set("{rom} stands for the patched ROM." + (f" Detected: {name}." if name else ""))
        else:
            hint.set(
                (f"Detected: {name}. " if name else "Emulator not recognized. ")
                + "Empty = default: " + core.emulator_defaults(path)
            )

    for k in ("emulator_path", "emulator_args"):
        vars_[k].trace_add("write", update_hint)
    vars_["target"].trace_add("write", show_target)
    update_hint()
    show_target()

    msg = tk.StringVar()
    ttk.Label(frame, textvariable=msg, foreground="#0a7").grid(row=10, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def save():
        cfg2 = {k: v.get().strip() for k, v in vars_.items()}
        miss = core.missing_settings(cfg2)
        if miss:
            messagebox.showerror("SMW Play Launcher", "Still missing: " + ", ".join(miss), parent=root)
            return
        if cfg2["target"] == "fxpak" and not cfg2["fxpak_port"].isdigit():
            messagebox.showerror("SMW Play Launcher", "The QUsb2Snes port must be a number (default 23074).", parent=root)
            return
        if not core.rom_looks_like_smw(cfg2["rom_path"]):
            if not messagebox.askyesno(
                "SMW Play Launcher",
                "This file does not look like the unmodified American Super Mario World ROM. "
                "Many patches need exactly that one. Save anyway?",
                parent=root,
            ):
                return
        core.save_config(cfg2)
        try:
            core.register_protocol()
        except OSError as e:
            messagebox.showwarning("SMW Play Launcher", f"Saved, but the smwplay:// link could not be registered: {e}", parent=root)
        msg.set("Saved. You can now press Play on a supported site.")
        if pending:
            root.destroy()
            run_play(pending)

    ttk.Button(frame, text="Save", command=save).grid(row=11, column=2, sticky="e", pady=(12, 0))
    gen = ttk.Label(frame, text="Link generator", foreground="#888", cursor="hand2", font=("Segoe UI", 8, "underline"))
    gen.grid(row=11, column=0, sticky="w", pady=(12, 0))
    gen.bind("<Button-1>", lambda _e: link_generator(root))
    if core.is_registered():
        msg.set("Registered as the handler for smwplay://.")
    root.mainloop()


def _mac_launch_url():
    """macOS passes smwplay:// links as an event, not as an argument. Wait briefly for it."""
    root = tk.Tk()
    root.withdraw()
    got = []
    root.createcommand("::tk::mac::LaunchURL", lambda *a: got.append(a[0]) if a else None)
    root.after(700, root.quit)
    root.mainloop()
    root.destroy()
    return got[0] if got else None


def main(argv) -> int:
    if len(argv) > 1 and argv[1].lower().startswith(core.SCHEME + ":"):
        return run_play(argv[1])
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        link = _mac_launch_url()
        if link and link.lower().startswith(core.SCHEME + ":"):
            return run_play(link)
    run_setup()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
