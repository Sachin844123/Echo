"""Bounded raster header inspection before any native decoder allocation."""

import struct
import zlib
from pathlib import Path

from app.ingestion.errors import ImportFailure


def image_header(path: Path, max_pixels: int) -> tuple[str, int, int]:
    with path.open("rb") as stream:
        header = stream.read(33)
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            if (len(header) != 33 or header[8:16] != b"\x00\x00\x00\rIHDR"
                    or zlib.crc32(header[12:29]) != int.from_bytes(header[29:33], "big")):
                raise ImportFailure("invalid_image", 415)
            width, height = struct.unpack(">II", header[16:24])
            mime = "image/png"
        elif header.startswith(b"\xff\xd8"):
            stream.seek(2)
            # Bound metadata/header scans too; reject pathological JPEG wrappers.
            while stream.tell() < 1024 * 1024:
                if stream.read(1) != b"\xff":
                    raise ImportFailure("invalid_image", 415)
                marker = stream.read(1)
                while marker == b"\xff" and stream.tell() < 1024 * 1024:
                    marker = stream.read(1)
                if not marker or marker in {b"\xd9", b"\xda"}:
                    raise ImportFailure("invalid_image", 415)
                length = int.from_bytes(stream.read(2), "big")
                if length < 2:
                    raise ImportFailure("invalid_image", 415)
                if marker[0] in {0xC0, 0xC1, 0xC2}:
                    frame = stream.read(5)
                    if len(frame) != 5 or length < 8:
                        raise ImportFailure("invalid_image", 415)
                    height, width = struct.unpack(">HH", frame[1:5])
                    mime = "image/jpeg"
                    break
                stream.seek(length - 2, 1)
            else:
                raise ImportFailure("invalid_image", 415)
        else:
            raise ImportFailure("invalid_image", 415)
    if width < 1 or height < 1:
        raise ImportFailure("invalid_image", 415)
    if width * height > max_pixels:
        raise ImportFailure("image_limit", 413)
    return mime, width, height
