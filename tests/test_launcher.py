import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bps  # noqa: E402
import core  # noqa: E402


def varint(x):
    out = bytearray()
    while True:
        x7 = x & 0x7F
        x >>= 7
        if x == 0:
            out.append(0x80 | x7)
            return bytes(out)
        out.append(x7)
        x -= 1


def make_patch(source, target, literal_at=None):
    """Kleiner Encoder: SourceRead für Gleiches, TargetRead für Abweichendes, danach TargetCopy."""
    body = bytearray()
    body += varint(len(source)) + varint(len(target)) + varint(0)
    i = 0
    while i < len(target):
        same = 0
        while i + same < len(target) and i + same < len(source) and target[i + same] == source[i + same]:
            same += 1
        if same:
            body += varint(((same - 1) << 2) | 0)
            i += same
            continue
        diff = 0
        while i + diff < len(target) and not (i + diff < len(source) and target[i + diff] == source[i + diff]):
            diff += 1
        body += varint(((diff - 1) << 2) | 1) + target[i:i + diff]
        i += diff
    body = bytes(body)
    head = b"BPS1" + body
    head += bps.crc32(source).to_bytes(4, "little") + bps.crc32(target).to_bytes(4, "little")
    return head + bps.crc32(head).to_bytes(4, "little")


SRC = bytes(range(256)) * 4
DST = SRC[:100] + b"HALLO WELT" + SRC[110:300] + b"\xff" * 20


def test_patch_roundtrip():
    assert bps.apply_bps(make_patch(SRC, DST), SRC) == DST


def test_wrong_rom():
    with pytest.raises(bps.BpsError) as e:
        bps.apply_bps(make_patch(SRC, DST), SRC[::-1])
    assert e.value.code == "wrong_source"


def test_damaged_patch():
    p = bytearray(make_patch(SRC, DST))
    p[10] ^= 0xFF
    with pytest.raises(bps.BpsError) as e:
        bps.apply_bps(bytes(p), SRC)
    assert e.value.code == "bad_patch"


def test_not_bps():
    with pytest.raises(bps.BpsError):
        bps.apply_bps(b"PATCH" + b"\0" * 40, SRC)


def test_copier_header_is_stripped():
    assert bps.strip_copier_header(b"\0" * (512 + 1024)) == b"\0" * 1024
    assert bps.strip_copier_header(b"\0" * 1024) == b"\0" * 1024


U = "https://spinjump.club/api/v1/hacks/a/download/1"


def test_parse_full_link():
    link = core.build_link(U, "spinjump:a@1", "Mein Hack", "AB" * 32)
    req = core.parse_url(link)
    assert req == {"url": U, "host": "spinjump.club", "id": "spinjump:a@1", "title": "Mein Hack", "sha256": "ab" * 32}


def test_generated_link_roundtrips_awkward_urls():
    u = "https://dl.smwcentral.net/1/Hack Name & Co.zip?x=1&y=2"
    assert core.parse_url(core.build_link(u))["url"] == u


@pytest.mark.parametrize(
    "link",
    [
        "https://play?url=" + U,
        "smwplay://other?url=" + U,
        "smwplay://play",
        "smwplay://play?url=http%3A%2F%2Fspinjump.club%2Fx",
        "smwplay://play?url=file%3A%2F%2F%2FC%3A%2Fx.bps",
        "smwplay://play?url=https%3A%2F%2Fuser%3Apw%40spinjump.club%2Fx",
        "smwplay://play?url=https%3A%2F%2Fspinjump.club%2Fx&id=..%2F..%2Fevil",
        "smwplay://play?url=https%3A%2F%2Fspinjump.club%2Fx&sha256=zz",
    ],
)
def test_parse_rejects_bad(link):
    with pytest.raises(core.LauncherError):
        core.parse_url(link)


def test_build_link_validates():
    for bad in ("http://x.de/a.bps", "ftp://x.de/a", "nonsense"):
        with pytest.raises(core.LauncherError):
            core.build_link(bad)
    with pytest.raises(core.LauncherError):
        core.build_link(U, id_="a b")
    with pytest.raises(core.LauncherError):
        core.build_link(U, sha256="123")


def test_host_trust_covers_subdomains_but_not_lookalikes():
    assert core.host_trusted("spinjump.club")
    assert core.host_trusted("dl.smwcentral.net")
    assert not core.host_trusted("evilspinjump.club")
    assert not core.host_trusted("spinjump.club.evil.example")
    assert not core.host_trusted("hacks.example.org")


def test_download_refuses_untrusted_host():
    with pytest.raises(core.LauncherError):
        core.download("https://evil.example/x.bps")


def test_redirect_to_untrusted_host_is_refused():
    h = core._TrustedRedirects()
    with pytest.raises(core.LauncherError):
        h.redirect_request(None, None, 302, "Found", {}, "https://evil.example/x.bps")
    with pytest.raises(core.LauncherError):
        h.redirect_request(None, None, 302, "Found", {}, "http://spinjump.club/x.bps")


def _cfg(tmp_path):
    rom = tmp_path / "smw.sfc"
    rom.write_bytes(SRC)
    return dict(core.DEFAULTS, rom_path=str(rom), hacks_dir=str(tmp_path / "hacks"))


def _zip(files):
    import io
    import zipfile

    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return b.getvalue()


def test_prepare_patches_and_reuses(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    calls = []
    monkeypatch.setattr(core, "download", lambda url, progress=None: calls.append(url) or make_patch(SRC, DST))
    req = core.parse_url(core.build_link(U, id_="a@1"))
    out = core.prepare(cfg, req)
    assert open(out, "rb").read() == DST
    core.prepare(cfg, req)
    assert len(calls) == 1


def test_prepare_zip_single_and_all_patches(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    patch = make_patch(SRC, DST)
    req = core.parse_url(core.build_link(U, id_="z"))
    monkeypatch.setattr(core, "download", lambda *a, **k: _zip({"readme.txt": "hi", "hack.bps": patch, "evil.exe": "MZ"}))
    out = core.prepare(cfg, req)
    assert open(out, "rb").read() == DST
    assert out == os.path.join(cfg["hacks_dir"], "hack", "hack.sfc")  # Ordner und Datei heißen wie die BPS-Datei

    # mehrere BPS: alle werden gepatcht, in einem Ordner; gefragt wird nur, welche startet
    cfg2 = dict(cfg, hacks_dir=str(tmp_path / "h2"))
    monkeypatch.setattr(core, "download", lambda *a, **k: _zip({"a.bps": patch, "sub/b.bps": patch}))
    with pytest.raises(core.LauncherError):
        core.prepare(cfg2, req)  # ohne Auswahl abgebrochen
    asked = []
    out = core.prepare(cfg2, req, choose=lambda names, last: asked.append((names, last)) or names[1])
    assert asked == [(["a", "b"], None)]
    folder = os.path.dirname(out)
    assert sorted(os.listdir(folder)) == ["a.sfc", "b.sfc"]
    assert os.path.basename(out) == "b.sfc"


def test_multi_zip_asks_again_but_never_downloads_or_patches_again(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    patch = make_patch(SRC, DST)
    calls = []
    monkeypatch.setattr(core, "download", lambda *a, **k: calls.append(1) or _zip({"a.bps": patch, "b.bps": patch}))
    req = core.parse_url(core.build_link(U, id_="x:two"))
    first = core.prepare(cfg, req, choose=lambda names, last: "b")
    seen = []
    second = core.prepare(cfg, req, choose=lambda names, last: seen.append(last) or "a")
    assert len(calls) == 1
    assert seen == ["b"]  # die zuletzt gestartete ist vorgewählt
    assert os.path.basename(first) == "b.sfc" and os.path.basename(second) == "a.sfc"
    third = core.prepare(cfg, req, choose=lambda names, last: last)
    assert os.path.basename(third) == "a.sfc"


def test_wrong_patch_in_zip_does_not_stop_the_others(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    good = make_patch(SRC, DST)
    other = make_patch(SRC[::-1], DST)  # für eine andere ROM gemacht
    monkeypatch.setattr(core, "download", lambda *a, **k: _zip({"good.bps": good, "other.bps": other}))
    req = core.parse_url(core.build_link(U, id_="x:mixed"))
    out = core.prepare(cfg, req, choose=lambda names, last: pytest.fail("nur ein Patch passt"))
    assert os.path.basename(out) == "good.sfc"


def test_zip_without_bps(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "download", lambda *a, **k: _zip({"a.ips": "x"}))
    with pytest.raises(core.LauncherError):
        core.prepare(_cfg(tmp_path), core.parse_url(core.build_link(U)))


def test_checksum_mismatch_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "download", lambda *a, **k: make_patch(SRC, DST))
    req = core.parse_url(core.build_link(U, sha256="0" * 64))
    with pytest.raises(core.LauncherError):
        core.prepare(_cfg(tmp_path), req)


def test_build_args():
    cfg = dict(core.DEFAULTS, emulator_args='--fullscreen "{rom}"')
    assert core.build_args(cfg, r"C:\a b\x.sfc") == ["--fullscreen", r"C:\a b\x.sfc"]
    assert core.build_args(dict(core.DEFAULTS, emulator_args="-x"), "r.sfc") == ["-x", "r.sfc"]


def test_config_roundtrip_ignores_old_trust_setting(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"rom_path": "X", "trusted_domains": "evil.example"}', encoding="utf-8")
    cfg = core.load_config(str(p))
    assert cfg["rom_path"] == "X" and "trusted_domains" not in cfg
    core.save_config(cfg, str(tmp_path / "d.json"))
    assert "trusted_domains" not in (tmp_path / "d.json").read_text(encoding="utf-8")


def test_detect_emulator():
    assert core.detect_emulator(r"D:\Emus\Mesen2\Mesen.exe") == "Mesen"
    assert core.detect_emulator(r"C:\x\snes9x-x64.exe") == "Snes9x"
    assert core.detect_emulator(r"C:\x\bsnes_hd.exe") == "bsnes"
    assert core.detect_emulator(r"C:\x\retroarch.exe") == "RetroArch"
    assert core.detect_emulator(r"C:\x\unknown.exe") is None
    assert core.detect_emulator("") is None


def test_default_args_per_emulator(tmp_path):
    assert core.emulator_defaults(r"C:\x\Mesen.exe") == '"{rom}"'
    ra = tmp_path / "retroarch.exe"
    (tmp_path / "cores").mkdir()
    (tmp_path / "cores" / "bsnes_libretro.dll").write_text("")
    args = core.build_args(dict(core.DEFAULTS, emulator_path=str(ra)), r"C:\h\a b.sfc")
    assert args == ["-L", str(tmp_path / "cores" / "bsnes_libretro.dll"), r"C:\h\a b.sfc"]
    (tmp_path / "cores" / "snes9x_libretro.dll").write_text("")  # bevorzugter Core
    assert "snes9x_libretro" in core.emulator_defaults(str(ra))


def test_explicit_args_win_over_defaults():
    cfg = dict(core.DEFAULTS, emulator_path=r"C:\x\Mesen.exe", emulator_args="--fullscreen {rom}")
    assert core.build_args(cfg, "r.sfc") == ["--fullscreen", "r.sfc"]


def test_zip_hack_is_not_downloaded_twice(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    patch = make_patch(SRC, DST)
    calls = []
    monkeypatch.setattr(core, "download", lambda *a, **k: calls.append(1) or _zip({"Hack.bps": patch}))
    req = core.parse_url(core.build_link(U, id_="smwcentral:hack-1"))
    first = core.prepare(cfg, req)
    assert first == os.path.join(cfg["hacks_dir"], "Hack", "Hack.sfc")  # Name wie die BPS-Datei
    status = []
    second = core.prepare(cfg, req, status.append)
    assert second == first and len(calls) == 1
    assert any("Already" in s for s in status)


def test_deleted_rom_is_fetched_again(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    calls = []
    monkeypatch.setattr(core, "download", lambda *a, **k: calls.append(1) or _zip({"h.bps": make_patch(SRC, DST)}))
    req = core.parse_url(core.build_link(U, id_="x:gone"))
    os.remove(core.prepare(cfg, req))
    core.prepare(cfg, req)
    assert len(calls) == 2


def test_library_ignores_paths_outside_hacks_dir(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    outside = tmp_path / "outside.sfc"
    outside.write_bytes(b"x")
    os.makedirs(cfg["hacks_dir"])
    with open(os.path.join(cfg["hacks_dir"], ".smwplay-library.json"), "w") as f:
        f.write('{"x:evil": "../outside.sfc"}')
    req = core.parse_url(core.build_link(U, id_="x:evil"))
    assert core.library_find(cfg, req) == ([], None)


def test_other_id_is_a_different_hack(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    calls = []
    monkeypatch.setattr(core, "download", lambda *a, **k: calls.append(1) or make_patch(SRC, DST))
    core.prepare(cfg, core.parse_url(core.build_link(U, id_="spinjump:a@1.0")))
    core.prepare(cfg, core.parse_url(core.build_link(U, id_="spinjump:a@1.1")))
    assert len(calls) == 2


def test_names_stay_readable_and_inside_hacks_dir(tmp_path):
    cfg = dict(core.DEFAULTS, hacks_dir=str(tmp_path))
    req = core.parse_url(core.build_link(U, id_="smwcentral:mario-s-inferno-42909", title="Mario's Inferno"))
    t = core.rom_targets(cfg, req, ["../../evil/Mario's Inferno.bps"])[0]
    assert t == os.path.join(str(tmp_path), "Mario's Inferno", "Mario's Inferno.sfc")
    assert core.rom_targets(cfg, req)[0] == os.path.join(str(tmp_path), "Mario's Inferno", "Mario's Inferno.sfc")
    two = core.rom_targets(cfg, req, ["a.bps", "sub/b.bps"])
    assert two == [os.path.join(str(tmp_path), "Mario's Inferno", n) for n in ("a.sfc", "b.sfc")]
    same = core.rom_targets(cfg, req, ["x/lvl.bps", "y/lvl.bps"])
    assert [os.path.basename(p) for p in same] == ["x-lvl.sfc", "y-lvl.sfc"]


def test_old_library_entries_and_old_file_names_are_ignored(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    os.makedirs(cfg["hacks_dir"])
    old = os.path.join(cfg["hacks_dir"], "smwcentral", "mario-s-inferno-42909-Mario_s_Inferno.sfc")
    os.makedirs(os.path.dirname(old))
    open(old, "wb").write(b"old")
    with open(os.path.join(cfg["hacks_dir"], ".smwplay-library.json"), "w") as f:
        f.write('{"smwcentral:mario-s-inferno-42909": {"files": ["smwcentral/mario-s-inferno-42909-Mario_s_Inferno.sfc"], "last": null}}')
    monkeypatch.setattr(core, "download", lambda *a, **k: _zip({"Mario's Inferno.bps": make_patch(SRC, DST)}))
    req = core.parse_url(core.build_link(U, id_="smwcentral:mario-s-inferno-42909"))
    out = core.prepare(cfg, req)
    assert out == os.path.join(cfg["hacks_dir"], "Mario's Inferno", "Mario's Inferno.sfc")
    assert open(out, "rb").read() == DST
