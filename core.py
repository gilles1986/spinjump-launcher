"""Kern des Launchers: Adresse lesen, Patch laden (nur von vertrauten Domains), patchen, starten.

Format: smwplay://play?url=<https-Adresse einer .bps oder .zip>[&id=…][&title=…][&sha256=…]
"""
import hashlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from bps import BpsError, apply_bps, crc32, strip_copier_header

SCHEME = "smwplay"
USER_AGENT = "SMWPlayLauncher/1.0"
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024
MAX_ZIP_ENTRIES = 500
SMW_USA_CRC = 0xB19ED489  # SMW (U) [!], ohne Header

# Vertraute Seiten pflegt allein der Betreiber von Spinjump (hier im Code, später evtl. eine signierte
# Liste von spinjump.club). Spieler tragen nichts ein. Eine Domain gilt samt Subdomains.
BUILTIN_TRUSTED = ("spinjump.club", "smwcentral.net")

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:@._+/-]{0,119}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

DEFAULTS = {
    "rom_path": "",
    "hacks_dir": "",
    "emulator_path": "",
    "emulator_args": "",  # leer = Voreinstellung passend zum Emulator (siehe emulator_defaults)
    "target": "emulator",  # "emulator" oder "fxpak"
    "fxpak_host": "localhost",
    "fxpak_port": "23074",
    "fxpak_device": "",  # leer = erstes Gerät
    "fxpak_folder": "/ROMS/Spinjump",
}


class LauncherError(Exception):
    pass


class FxpakUnavailable(LauncherError):
    """QUsb2Snes wurde nicht gefunden. Der Aufrufer darf anbieten, es erneut zu versuchen oder zum Emulator zu wechseln."""


# ---- Einstellungen ----

def config_dir() -> str:
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.join(base, "Spinjump")


def config_path() -> str:
    return os.path.join(config_dir(), "launcher.json")


def load_config(path=None) -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(path or config_path(), encoding="utf-8") as f:
            data = json.load(f)
        cfg.update({k: v for k, v in data.items() if k in DEFAULTS and isinstance(v, str)})
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict, path=None) -> None:
    path = path or config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: cfg.get(k, v) for k, v in DEFAULTS.items()}, f, indent=2)


def missing_settings(cfg: dict) -> list:
    """Pflichtfelder, die noch fehlen. Der Emulator ist optional (dann öffnet Windows die ROM)."""
    out = []
    if not os.path.isfile(cfg["rom_path"]):
        out.append("Super Mario World ROM")
    if not cfg["hacks_dir"]:
        out.append("Hacks folder")
    return out


def rom_looks_like_smw(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return crc32(strip_copier_header(f.read())) == SMW_USA_CRC
    except OSError:
        return False


# ---- Vertraute Domains ----

def host_trusted(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in BUILTIN_TRUSTED)


# ---- Emulatoren: passende Argumente je nach Programm ----

# Reihenfolge: bevorzugter Core zuerst. Name in cores/ ohne Endung.
RETROARCH_CORES = ("snes9x_libretro", "bsnes_libretro", "bsnes_hd_beta_libretro", "mesen-s_libretro", "snes9x2010_libretro")

EMULATORS = (
    ("mesen", "Mesen"),
    ("snes9x", "Snes9x"),
    ("bsnes", "bsnes"),
    ("higan", "higan"),
    ("ares", "ares"),
    ("zsnes", "ZSNES"),
    ("retroarch", "RetroArch"),
)


def detect_emulator(path: str):
    """Name des Emulators nach dem Dateinamen, sonst None."""
    name = os.path.splitext(os.path.basename(path or ""))[0].lower()
    for key, label in EMULATORS:
        if key in name:
            return label
    return None


def emulator_defaults(path: str) -> str:
    """Voreingestellte Argumente für einen Emulator. {rom} steht für die gepatchte ROM."""
    if detect_emulator(path) == "RetroArch":
        cores = os.path.join(os.path.dirname(path), "cores")
        for core_name in RETROARCH_CORES:
            ext = ".dll" if sys.platform == "win32" else ".dylib" if sys.platform == "darwin" else ".so"
            candidate = os.path.join(cores, core_name + ext)
            if os.path.isfile(candidate):
                return f'-L "{candidate}" "{{rom}}"'
        return '"{rom}"'  # ohne Core fragt RetroArch selbst
    return '"{rom}"'


# ---- Adresse lesen und erzeugen ----

def check_download_url(url: str) -> str:
    """Gibt den Host zurück. Nur https, kein Benutzername, ein richtiger Host."""
    if len(url) > 2000:
        raise LauncherError("The address is too long.")
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        raise LauncherError("The patch address must be an https address.")
    return u.hostname.lower()


def parse_url(link: str) -> dict:
    u = urllib.parse.urlsplit(link.strip())
    if u.scheme.lower() != SCHEME or u.netloc.lower().rstrip("/") != "play":
        raise LauncherError("This is not a play address.")
    q = urllib.parse.parse_qs(u.query)
    one = lambda k: (q.get(k) or [None])[0] or None  # noqa: E731
    url, id_, title, sha = one("url"), one("id"), one("title"), one("sha256")
    if not url:
        raise LauncherError("The address is missing the link to the patch.")
    host = check_download_url(url)
    if id_ and not ID_RE.match(id_):
        raise LauncherError("The address contains an invalid ID.")
    if title is not None:
        title = "".join(c for c in title if c.isprintable())[:100] or None
    if sha and not SHA256_RE.match(sha):
        raise LauncherError("The address contains an invalid checksum.")
    return {"url": url, "host": host, "id": id_, "title": title, "sha256": sha.lower() if sha else None}


def build_link(url: str, id_=None, title=None, sha256=None) -> str:
    """Link-Generator: aus einer Patch-Adresse den Protokoll-Link bauen (und dabei prüfen)."""
    url = url.strip()
    check_download_url(url)
    q = [("url", url)]
    if id_ and id_.strip():
        if not ID_RE.match(id_.strip()):
            raise LauncherError("The ID may only contain letters, digits and : @ . _ + / -")
        q.append(("id", id_.strip()))
    if title and title.strip():
        q.append(("title", title.strip()[:100]))
    if sha256 and sha256.strip():
        if not SHA256_RE.match(sha256.strip()):
            raise LauncherError("The SHA-256 checksum must consist of 64 hex characters.")
        q.append(("sha256", sha256.strip().lower()))
    return f"{SCHEME}://play?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)


# ---- Laden ----

def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._+-]+", "_", name).strip("._") or "patch"


def _clean(name: str) -> str:
    """Dateiname so lesbar wie möglich: Leerzeichen und Apostrophe bleiben, nur Unzulässiges fällt weg."""
    cleaned = re.sub(r'[<>:"/\|?*\x00-\x1f]+', "_", name).strip(" .")
    return cleaned or "patch"


def _stem(path: str) -> str:
    return _clean(os.path.splitext(path.replace("\\", "/").rsplit("/", 1)[-1])[0])


def hack_name(req: dict) -> str:
    """Name des Hacks, wenn keine BPS-Datei ihn liefert: Titel, sonst Kennung, sonst Host und Hash der Adresse."""
    if req.get("title"):
        return _clean(req["title"])
    if req["id"]:
        return _clean(req["id"].partition(":")[2] or req["id"])
    return _clean(req["host"]) + "-" + hashlib.sha1(req["url"].encode()).hexdigest()[:10]


def rom_targets(cfg: dict, req: dict, members=None) -> list:
    """Ablageorte der gepatchten ROMs: <Hacks-Ordner>/<Name>/<Name>.sfc, benannt wie die BPS-Datei.

    Ein ZIP mit mehreren Patches: Ordner nach dem Hack, darin je Patch eine .sfc nach dem Namen der .bps.
    Ohne Dateinamen (direkter Link): Titel oder Kennung.
    """
    base = cfg["hacks_dir"]
    if not members:
        name = hack_name(req)
        return [os.path.join(base, name, name + ".sfc")]
    if len(members) == 1:
        name = _stem(members[0])
        return [os.path.join(base, name, name + ".sfc")]
    folder = os.path.join(base, hack_name(req))
    stems = [_stem(m) for m in members]
    if len(set(stems)) < len(stems):  # gleiche Namen in verschiedenen Unterordnern: Pfad mit dazunehmen
        stems = [_clean(os.path.splitext(m.replace("\\", "/"))[0].replace("/", "-")) for m in members]
    return [os.path.join(folder, st + ".sfc") for st in stems]


# ---- Bibliothek: welche Kennung ist schon gepatcht? ----
# Der Dateiname eines ZIP-Hacks hängt vom Inhalt des ZIP ab. Damit man vor dem Laden weiß, ob es
# den Hack schon gibt, merkt sich eine kleine Datei im Hacks-Ordner zu jeder Kennung die fertigen
# ROMs (bei mehreren Patches im ZIP alle) und die zuletzt gestartete.

def cache_key(req: dict) -> str:
    # "v2|": Bibliothekseinträge aus dem früheren Namensschema werden ignoriert (sonst startet die alte ROM)
    return "v2|" + (req["id"] or "url:" + hashlib.sha1(req["url"].encode()).hexdigest())


def _library_file(cfg: dict) -> str:
    return os.path.join(cfg["hacks_dir"], ".smwplay-library.json")


def _library_read(cfg: dict) -> dict:
    try:
        with open(_library_file(cfg), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _inside_hacks_dir(cfg: dict, rel) -> str:
    """Absoluter Pfad, wenn er im Hacks-Ordner liegt und existiert, sonst ''."""
    if not isinstance(rel, str):
        return ""
    path = os.path.normpath(os.path.join(cfg["hacks_dir"], rel))
    ok = path.startswith(os.path.normpath(cfg["hacks_dir"]) + os.sep) and os.path.isfile(path)
    return path if ok else ""


def library_find(cfg: dict, req: dict):
    """(vorhandene ROMs, zuletzt gestartete oder None) zu dieser Kennung."""
    entry = _library_read(cfg).get(cache_key(req))
    files, last = [], None
    if isinstance(entry, dict):
        files = [p for p in (_inside_hacks_dir(cfg, r) for r in entry.get("files") or []) if p]
        last = _inside_hacks_dir(cfg, entry.get("last")) or None
    return files, (last if last in files else None)


def library_set(cfg: dict, req: dict, files: list, last=None) -> None:
    data = _library_read(cfg)
    rel = lambda p: os.path.relpath(p, cfg["hacks_dir"]).replace("\\", "/")  # noqa: E731
    data[cache_key(req)] = {"files": [rel(p) for p in files], "last": rel(last) if last else None}
    os.makedirs(cfg["hacks_dir"], exist_ok=True)
    with open(_library_file(cfg), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)


def rom_label(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


class _TrustedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = check_download_url(newurl)
        if not host_trusted(host):
            raise LauncherError(f"Redirect to {host} aborted: the domain is not trusted.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str, progress=None) -> bytes:
    host = check_download_url(url)
    if not host_trusted(host):
        raise LauncherError(f"{host} is not on the list of trusted sites and will not be downloaded.")
    opener = urllib.request.build_opener(_TrustedRedirects())
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=30) as r:
            total = int(r.headers.get("Content-Length") or 0)
            if total > MAX_DOWNLOAD_BYTES:
                raise LauncherError("The file is unusually large, aborting.")
            buf = bytearray()
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > MAX_DOWNLOAD_BYTES:
                    raise LauncherError("The file is unusually large, aborting.")
                if progress and total:
                    progress(len(buf) / total)
            return bytes(buf)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise LauncherError("This file no longer exists on the site.")
        raise LauncherError(f"The site responded with error {e.code}.")
    except urllib.error.URLError as e:
        if isinstance(e.reason, LauncherError):
            raise e.reason
        raise LauncherError(f"Could not connect to the site: {e.reason}")
    except OSError as e:
        raise LauncherError(f"Could not connect to the site: {e}")


def bps_members(data: bytes) -> dict:
    """Aus einem ZIP die .bps-Dateien lesen (nur im Speicher, nichts wird entpackt oder ausgeführt)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        infos = z.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise LauncherError("The ZIP contains an unusually large number of files.")
        out, total = {}, 0
        for i in infos:
            if i.is_dir() or not i.filename.lower().endswith(".bps"):
                continue
            total += i.file_size
            if i.file_size > MAX_DOWNLOAD_BYTES or total > MAX_DOWNLOAD_BYTES:
                raise LauncherError("The ZIP unpacks to an unusually large size, aborting.")
            out[i.filename] = z.read(i)
        return out
    except zipfile.BadZipFile:
        raise LauncherError("The ZIP is damaged.")


def _pick(cfg: dict, req: dict, files: list, last, choose) -> str:
    """Bei mehreren fertigen ROMs fragen, welche gestartet wird (die letzte ist vorgewählt)."""
    if len(files) == 1:
        chosen = files[0]
    else:
        labels = {rom_label(p): p for p in files}
        name = choose(sorted(labels), rom_label(last) if last else None) if choose else None
        if name not in labels:
            raise LauncherError("Cancelled.")
        chosen = labels[name]
    library_set(cfg, req, files, chosen)
    return chosen


def _patch_to(rom: bytes, patch: bytes, target: str) -> None:
    result = apply_bps(patch, rom)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".part"
    with open(tmp, "wb") as f:
        f.write(result)
    os.replace(tmp, target)


def prepare(cfg: dict, req: dict, status=lambda s: None, progress=None, choose=None) -> str:
    """Lädt und patcht, falls nötig. Gibt den Pfad der ROM zurück, die gestartet werden soll.

    Enthält ein ZIP mehrere BPS-Patches, werden alle gepatcht und in einem Ordner abgelegt;
    choose(namen, vorgewählt) -> name sagt, welche gestartet wird (None = abgebrochen).
    Was schon da ist, wird weder geladen noch neu gepatcht.
    """
    files, last = library_find(cfg, req)
    if files:
        status("Already downloaded, starting …")
        return _pick(cfg, req, files, last, choose)
    status("Downloading …")
    data = download(req["url"], progress)
    if req["sha256"] and hashlib.sha256(data).hexdigest() != req["sha256"]:
        raise LauncherError("The file's checksum does not match the link. Aborting.")
    if data[:2] == b"PK":
        members = bps_members(data)
        if not members:
            raise LauncherError("There is no .bps file in the ZIP. The launcher can only apply BPS patches.")
        names = sorted(members)
        targets = dict(zip(rom_targets(cfg, req, names), (members[m] for m in names)))
    else:
        targets = {rom_targets(cfg, req)[0]: data}
    try:
        with open(cfg["rom_path"], "rb") as f:
            rom = strip_copier_header(f.read())
    except OSError as e:
        raise LauncherError(f"Could not read the ROM: {e}")
    done, first_error = [], None
    for i, (target, patch) in enumerate(targets.items(), 1):
        status(f"Patching ({i}/{len(targets)}) …" if len(targets) > 1 else "Patching …")
        try:
            _patch_to(rom, patch, target)
            done.append(target)
        except BpsError as e:
            first_error = first_error or e  # ein unpassender Patch im ZIP stoppt die anderen nicht
        except OSError as e:
            raise LauncherError(f"Could not write the ROM: {e}")
    if not done:
        hint = " Check the ROM in the settings." if first_error.code == "wrong_source" else ""
        raise LauncherError(str(first_error) + hint)
    return _pick(cfg, req, done, None, choose)


def build_args(cfg: dict, rom: str) -> list:
    template = cfg["emulator_args"] or emulator_defaults(cfg["emulator_path"])
    args = [a.replace("{rom}", rom) for a in shlex.split(template, posix=False)]
    args = [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a for a in args]
    if not any(rom in a for a in args):
        args.append(rom)
    return args


def switch_to_emulator(cfg: dict, path=None) -> None:
    """Merkt sich dauerhaft, dass auf dem Emulator gespielt wird (z. B. wenn QUsb2Snes fehlte)."""
    cfg["target"] = "emulator"
    save_config(cfg, path)


def launch(cfg: dict, rom: str, status=lambda s: None, progress=None) -> None:
    if cfg.get("target") == "fxpak":
        import fxpak

        try:
            fxpak.play(cfg, rom, status, progress)
        except fxpak.FxpakUnreachable as e:
            raise FxpakUnavailable(str(e))
        except fxpak.FxpakError as e:
            raise LauncherError(str(e))
        return
    emu = cfg["emulator_path"]
    if not emu:
        if hasattr(os, "startfile"):
            os.startfile(rom)  # Standardprogramm für .sfc
            return
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        try:
            subprocess.Popen([opener, rom])
        except OSError:
            raise LauncherError("No emulator configured.")
        return
    if sys.platform == "darwin" and emu.rstrip("/").endswith(".app") and os.path.isdir(emu):
        subprocess.Popen(["open", "-a", emu, "--args", *build_args(cfg, rom)])
        return
    if not os.path.isfile(emu):
        raise LauncherError("The emulator was not found. Check the settings.")
    subprocess.Popen([emu, *build_args(cfg, rom)], cwd=os.path.dirname(emu))


# ---- Adresse "smwplay://" beim System anmelden ----

def register_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'
    exe = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{exe}" "{os.path.abspath(sys.argv[0])}" "%1"'


def _desktop_file() -> str:
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(data, "applications", "smwplay.desktop")


def _desktop_entry() -> str:
    if getattr(sys, "frozen", False):
        exec_ = shlex.quote(sys.executable)
    else:
        exec_ = f"{shlex.quote(sys.executable)} {shlex.quote(os.path.abspath(sys.argv[0]))}"
    return (
        "[Desktop Entry]\nType=Application\nName=SMW Play Launcher\n"
        f"Exec={exec_} %u\nNoDisplay=true\nTerminal=false\n"
        f"MimeType=x-scheme-handler/{SCHEME};\n"
    )


def register_protocol() -> None:
    if sys.platform == "win32":
        import winreg  # nur Windows

        root = rf"Software\Classes\{SCHEME}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root) as k:
            winreg.SetValue(k, "", winreg.REG_SZ, "URL:SMW Play")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root + r"\shell\open\command") as k:
            winreg.SetValue(k, "", winreg.REG_SZ, register_command())
    elif sys.platform == "darwin":
        pass  # macOS kennt die Adresse über die Info.plist der .app (siehe launcher/build.md), nichts zu tun
    else:
        path = _desktop_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(_desktop_entry())
        try:
            subprocess.run(
                ["xdg-mime", "default", "smwplay.desktop", f"x-scheme-handler/{SCHEME}"], check=False, timeout=10
            )
        except (OSError, subprocess.SubprocessError):
            pass


def is_registered() -> bool:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{SCHEME}\shell\open\command") as k:
                return winreg.QueryValue(k, "") == register_command()
        except (OSError, ImportError):
            return False
    if sys.platform == "darwin":
        return getattr(sys, "frozen", False)  # als .app gebaut = angemeldet
    try:
        with open(_desktop_file(), encoding="utf-8") as f:
            return f.read() == _desktop_entry()
    except OSError:
        return False
