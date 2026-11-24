import json
import os
import sys
import threading

import pytest
from websockets.sync.server import serve

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core  # noqa: E402
import fxpak  # noqa: E402


class FakeQusb:
    """A small QUsb2Snes server: file system as a dict, records the commands."""

    def __init__(self, devices=("FXPak Pro",), existing=None):
        self.devices = list(devices)
        self.dirs = {"/", "/ROMS"}
        self.files = dict(existing or {})
        self.log = []
        self.running = ""
        self.server = serve(self.handle, "127.0.0.1", 0)
        self.port = self.server.socket.getsockname()[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def children(self, path):
        path = path.rstrip("/") or "/"
        out = []
        for d in self.dirs:
            if d != "/" and d.rpartition("/")[0] in (path, "") and (d.rpartition("/")[0] or "/") == path:
                out += ["0", d.rpartition("/")[2]]
        for f in self.files:
            if (f.rpartition("/")[0] or "/") == path:
                out += ["1", f.rpartition("/")[2]]
        return out

    def handle(self, ws):
        pending = None  # (path, bytes still expected, collected)
        for msg in ws:
            if pending:
                path, left, buf = pending
                buf += msg
                left -= len(msg)
                pending = (path, left, buf) if left > 0 else None
                if not pending:
                    self.files[path] = buf
                continue
            cmd = json.loads(msg)
            op, args = cmd["Opcode"], cmd.get("Operands") or []
            self.log.append((op, args))
            if op == "DeviceList":
                ws.send(json.dumps({"Results": self.devices}))
            elif op == "Info":
                ws.send(json.dumps({"Results": ["2.0", "", self.running]}))
            elif op == "List":
                if args[0].rstrip("/") not in self.dirs and args[0] != "/":
                    ws.close()  # like the SD2SNES does for a missing directory
                    return
                ws.send(json.dumps({"Results": self.children(args[0])}))
            elif op == "MakeDir":
                self.dirs.add(args[0])
            elif op == "PutFile":
                pending = (args[0], int(args[1], 16), b"")
            elif op == "Boot":
                self.running = args[0].rsplit("/", 1)[-1]

    def close(self):
        self.server.shutdown()


@pytest.fixture
def qusb():
    s = FakeQusb()
    yield s
    s.close()


def _cfg(tmp_path, qusb, **kw):
    hacks = tmp_path / "hacks"
    (hacks / "spinjump").mkdir(parents=True)
    rom = hacks / "spinjump" / "made-of-fantasy_1.0.sfc"
    rom.write_bytes(os.urandom(100_000))
    cfg = dict(core.DEFAULTS, hacks_dir=str(hacks), target="fxpak", fxpak_port=str(qusb.port), **kw)
    return cfg, str(rom)


def test_remote_path_is_safe():
    assert fxpak.remote_path("/ROMS/Spinjump", "spinjump\\made-of-fantasy_1.0.sfc") == "/ROMS/Spinjump/spinjump/made-of-fantasy_1.0.sfc"
    assert fxpak.remote_path("../..", "../a:b.sfc") == "/a_b.sfc"


def test_uploads_creates_folders_and_boots(tmp_path, qusb):
    cfg, rom = _cfg(tmp_path, qusb)
    status = []
    fxpak.play(cfg, rom, status.append, sleep=lambda s: None)
    remote = "/ROMS/Spinjump/spinjump/made-of-fantasy_1.0.sfc"
    assert qusb.files[remote] == open(rom, "rb").read()
    ops = [o for o, _ in qusb.log]
    assert ops.index("PutFile") < ops.index("Boot")
    assert ("Boot", [remote]) in qusb.log
    assert ("Attach", ["FXPak Pro"]) in qusb.log
    assert {"/ROMS/Spinjump", "/ROMS/Spinjump/spinjump"} <= qusb.dirs
    assert any("Copying" in s for s in status)


def test_existing_file_is_not_uploaded_again(tmp_path, qusb):
    cfg, rom = _cfg(tmp_path, qusb)
    fxpak.play(cfg, rom, sleep=lambda s: None)
    qusb.log.clear()
    fxpak.play(cfg, rom, sleep=lambda s: None)
    ops = [o for o, _ in qusb.log]
    assert "PutFile" not in ops and "Boot" in ops


def test_no_device(tmp_path):
    q = FakeQusb(devices=())
    try:
        cfg, rom = _cfg(tmp_path, q)
        with pytest.raises(fxpak.FxpakUnreachable, match="No device"):
            fxpak.play(cfg, rom, sleep=lambda s: None)
    finally:
        q.close()


def test_qusb_not_running(tmp_path):
    cfg = dict(core.DEFAULTS, hacks_dir=str(tmp_path), target="fxpak", fxpak_port="1")
    with pytest.raises(fxpak.FxpakError, match="not reachable"):
        fxpak.play(cfg, str(tmp_path / "a.sfc"), sleep=lambda s: None)


def test_launch_routes_to_fxpak_and_wraps_errors(tmp_path):
    cfg = dict(core.DEFAULTS, hacks_dir=str(tmp_path), target="fxpak", fxpak_port="1")
    with pytest.raises(core.LauncherError, match="not reachable"):
        core.launch(cfg, str(tmp_path / "a.sfc"))


def test_unreachable_is_its_own_error_for_the_fallback_dialog(tmp_path):
    cfg = dict(core.DEFAULTS, hacks_dir=str(tmp_path), target="fxpak", fxpak_port="1")
    with pytest.raises(core.FxpakUnavailable):
        core.launch(cfg, str(tmp_path / "a.sfc"))
    q = FakeQusb(devices=())  # QUsb2Snes runs but no device: offer the switch then too
    try:
        cfg2, rom = _cfg(tmp_path, q)
        with pytest.raises(core.FxpakUnavailable, match="No device"):
            core.launch(cfg2, rom)
    finally:
        q.close()


def test_switch_to_emulator_is_remembered(tmp_path):
    p = str(tmp_path / "c.json")
    cfg = dict(core.DEFAULTS, target="fxpak", rom_path="X")
    core.switch_to_emulator(cfg, p)
    assert core.load_config(p)["target"] == "emulator"
    assert cfg["target"] == "emulator"
