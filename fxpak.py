"""FXPak Pro via QUsb2Snes: put the ROM on the SD card and start it.

QUsb2Snes (runs on the PC) offers a WebSocket at ws://localhost:23074. Flow as in the
SMWC Downloader & Patcher: Name, DeviceList, Attach, (MakeDir), PutFile, Info (waits until the
file is written), Boot. The SD2SNES closes the connection when a missing directory is listed,
so the parent directory is always listed instead.
"""
import json
import os
import time

from websockets.sync.client import connect as ws_connect

APP_NAME = "SMW Play Launcher"
INVALID = '<>:"/\\|?*'
CHUNK = 32 * 1024


class FxpakError(Exception):
    pass


class FxpakUnreachable(FxpakError):
    """QUsb2Snes is not running, not reachable, or finds no device (the launcher then asks the user)."""


def safe_name(name: str) -> str:
    cleaned = "".join("_" if (c in INVALID or ord(c) < 32) else c for c in name)
    return cleaned.strip().rstrip(".") or "_"


def remote_path(folder: str, rel_path: str) -> str:
    """Target path on the device: <folder>/<subfolder>/<file>, forward slashes only."""
    parts = [p for p in folder.replace("\\", "/").split("/") if p and p not in (".", "..")]
    parts += [safe_name(p) for p in rel_path.replace("\\", "/").split("/") if p and p not in (".", "..")]
    return "/" + "/".join(parts)


class Client:
    def __init__(self, host: str, port: int, connect=ws_connect, sleep=time.sleep):
        self.sleep = sleep
        try:
            self.ws = connect(f"ws://{host}:{port}", open_timeout=5, max_size=None)
        except Exception as e:
            raise FxpakUnreachable(
                "QUsb2Snes is not reachable. Start QUsb2Snes and close other programs "
                f"that use the FXPak. ({e})"
            )
        self._send("Name", [APP_NAME])

    def _send(self, opcode, operands=None):
        cmd = {"Opcode": opcode, "Space": "SNES"}
        if operands:
            cmd["Operands"] = operands
        self.ws.send(json.dumps(cmd))

    def _ask(self, opcode, operands=None, timeout=10.0):
        self._send(opcode, operands)
        try:
            return json.loads(self.ws.recv(timeout=timeout))
        except TimeoutError:
            raise FxpakError(
                f"No response to {opcode}. Another program is probably using the FXPak "
                "(RetroAchievements, QFile2Snes …)."
            )
        except Exception as e:
            raise FxpakError(f"Lost connection to QUsb2Snes: {e}")

    def attach(self, device: str = ""):
        if not device:
            devices = self._ask("DeviceList").get("Results") or []
            if not devices:
                raise FxpakUnreachable("No device found. Is the FXPak connected and turned on?")
            device = devices[0]
        self._send("Attach", [device])
        self.sleep(0.3)
        self._ask("Info", timeout=8.0)  # checks that the device answers
        return device

    def list_dir(self, path: str) -> list:
        results = self._ask("List", [path], timeout=15.0).get("Results") or []
        out = []
        for i in range(0, len(results) - 1, 2):
            if results[i + 1] not in (".", ".."):
                out.append((results[i + 1], results[i] == "0"))  # (Name, ist_Ordner)
        return out

    def ensure_dir(self, path: str):
        current = ""
        for part in [p for p in path.split("/") if p]:
            existing = {n.lower(): n for n, is_dir in self.list_dir(current or "/") if is_dir}
            current += "/" + existing.get(part.lower(), part)
            if part.lower() not in existing:
                self._send("MakeDir", [current])
                self.sleep(0.3)

    def dir_exists(self, path: str) -> bool:
        """Checks via the parent directory, never by listing the one searched for (the SD2SNES disconnects then)."""
        current = ""
        for part in [p for p in path.split("/") if p]:
            existing = {n.lower(): n for n, is_dir in self.list_dir(current or "/") if is_dir}
            if part.lower() not in existing:
                return False
            current += "/" + existing[part.lower()]
        return True

    def file_exists(self, path: str) -> bool:
        folder, _, name = path.rpartition("/")
        if not self.dir_exists(folder):
            return False
        return any(n.lower() == name.lower() and not d for n, d in self.list_dir(folder or "/"))

    def put_file(self, local: str, path: str, progress=None):
        size = os.path.getsize(local)
        self._send("PutFile", [path, format(size, "X")])
        self.sleep(0.1)
        sent = 0
        with open(local, "rb") as f:
            while chunk := f.read(CHUNK):
                self.ws.send(chunk)
                sent += len(chunk)
                if progress:
                    progress(sent / size)
        self._ask("Info", timeout=120.0)  # only answers once the file is written

    def boot(self, path: str) -> bool:
        """Starts the ROM. Boot has no reply; Info runs afterwards and shows what is running."""
        self._send("Boot", [path])
        wanted = path.rsplit("/", 1)[-1].lower()
        for _ in range(3):
            results = self._ask("Info", timeout=20.0).get("Results") or []
            if wanted in " ".join(str(r) for r in results).replace("\x00", "").lower():
                return True
            self.sleep(1.0)
        return False

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def play(cfg: dict, local_rom: str, status=lambda s: None, progress=None, connect=ws_connect, sleep=time.sleep) -> None:
    """Puts the ROM on the FXPak if needed and starts it there."""
    try:
        port = int(cfg.get("fxpak_port") or 23074)
    except ValueError:
        raise FxpakError("The QUsb2Snes port is not a number.")
    rel = os.path.relpath(local_rom, cfg["hacks_dir"])
    path = remote_path(cfg.get("fxpak_folder") or "/ROMS/Spinjump", rel)
    status("Connecting to the FXPak …")
    client = Client(cfg.get("fxpak_host") or "localhost", port, connect, sleep)
    try:
        client.attach(cfg.get("fxpak_device", ""))
        if client.file_exists(path):
            status("Already on the FXPak, starting …")
        else:
            status("Copying to the FXPak …")
            client.ensure_dir(path.rpartition("/")[0])
            client.put_file(local_rom, path, progress)
            status("Starting …")
        if not client.boot(path):
            raise FxpakError("The start command was sent, but the FXPak does not report the ROM as running.")
    finally:
        client.close()
