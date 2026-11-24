"""Apply BPS patches (Flips/beat format), standard library only."""
import zlib

MAX_TARGET_BYTES = 64 * 1024 * 1024


class BpsError(Exception):
    """code: bad_patch | wrong_source | bad_result"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def crc32(data) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def strip_copier_header(rom: bytes) -> bytes:
    """Some ROMs carry a 512-byte copier header. It is not part of the patch."""
    if len(rom) > 512 and len(rom) % 1024 == 512:
        return rom[512:]
    return rom


def apply_bps(patch: bytes, source: bytes) -> bytes:
    if len(patch) < 19 or patch[:4] != b"BPS1":
        raise BpsError("bad_patch", "This is not a BPS patch.")
    end = len(patch) - 12
    if crc32(patch[:-4]) != int.from_bytes(patch[-4:], "little"):
        raise BpsError("bad_patch", "The patch is damaged (checksum mismatch).")
    pos = 4

    def varint() -> int:
        nonlocal pos
        x, shift = 0, 1
        while True:
            if pos >= end:
                raise BpsError("bad_patch", "The patch is truncated.")
            b = patch[pos]
            pos += 1
            x += (b & 0x7F) * shift
            if b & 0x80:
                return x
            shift <<= 7
            x += shift

    source_size, target_size, meta_size = varint(), varint(), varint()
    if target_size > MAX_TARGET_BYTES:
        raise BpsError("bad_patch", "The patch asks for an impossibly large result.")
    pos += meta_size
    if len(source) != source_size or crc32(source) != int.from_bytes(patch[end:end + 4], "little"):
        raise BpsError("wrong_source", "This is not the ROM the patch was made for.")

    out = bytearray(target_size)
    o = src_rel = tgt_rel = 0
    while pos < end:
        data = varint()
        cmd, length = data & 3, (data >> 2) + 1
        if o + length > target_size:
            raise BpsError("bad_patch", "The patch writes past the end.")
        if cmd == 0:  # SourceRead
            if o + length > len(source):
                raise BpsError("bad_patch", "The patch reads past the end of the ROM.")
            out[o:o + length] = source[o:o + length]
        elif cmd == 1:  # TargetRead
            if pos + length > end:
                raise BpsError("bad_patch", "The patch is truncated.")
            out[o:o + length] = patch[pos:pos + length]
            pos += length
        else:
            off = varint()
            off = -(off >> 1) if off & 1 else off >> 1
            if cmd == 2:  # SourceCopy
                src_rel += off
                if src_rel < 0 or src_rel + length > len(source):
                    raise BpsError("bad_patch", "The patch points to nothing.")
                out[o:o + length] = source[src_rel:src_rel + length]
                src_rel += length
            else:  # TargetCopy (may overlap)
                tgt_rel += off
                if tgt_rel < 0 or tgt_rel >= o:
                    raise BpsError("bad_patch", "The patch points to nothing.")
                for i in range(length):
                    out[o + i] = out[tgt_rel + i]
                tgt_rel += length
        o += length
    if o != target_size or crc32(out) != int.from_bytes(patch[end + 4:end + 8], "little"):
        raise BpsError("bad_result", "The result does not match what the author built.")
    return bytes(out)
