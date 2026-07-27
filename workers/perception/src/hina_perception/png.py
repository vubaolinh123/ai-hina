"""Bounded, dependency-free PNG decoding for snapshot evidence.

M08-S1 only needs enough pixel access to build privacy-preserving evidence:
image dimensions, mean luminance and a 9x8 luma grid for perceptual dedup.
The decoder therefore supports exactly the PNG subset that browsers emit from
``canvas.toBlob("image/png")``: 8-bit depth, color types 0/2/3/4/6, no
interlacing. Anything else is rejected instead of guessed at, and raw pixel
data never leaves this module.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from .errors import PerceptionError


_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
_GRID_COLUMNS = 9
_GRID_ROWS = 8


@dataclass(frozen=True, slots=True)
class SnapshotSummary:
    """Renderer-safe evidence derived from one snapshot; carries no pixels."""

    width: int
    height: int
    mean_luma: int
    luma_grid: tuple[tuple[int, ...], ...]


def summarize_png(
    data: bytes,
    *,
    max_bytes: int,
    max_dimension: int,
    min_dimension: int,
) -> SnapshotSummary:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise PerceptionError("E_PERCEPTION_SNAPSHOT_INVALID", "snapshot body is empty")
    if len(data) > max_bytes:
        raise PerceptionError(
            "E_PERCEPTION_SNAPSHOT_TOO_LARGE",
            f"snapshot exceeds the {max_bytes} byte limit",
        )
    if not data.startswith(_SIGNATURE):
        raise PerceptionError("E_PERCEPTION_SNAPSHOT_INVALID", "snapshot is not a PNG image")

    width = height = 0
    bit_depth = color_type = interlace = -1
    palette: bytes | None = None
    idat = bytearray()
    saw_ihdr = saw_iend = False
    offset = len(_SIGNATURE)
    view = memoryview(data)

    while offset + 8 <= len(data):
        length = int.from_bytes(view[offset : offset + 4], "big")
        chunk_type = bytes(view[offset + 4 : offset + 8])
        chunk_start = offset + 8
        chunk_end = chunk_start + length
        if length > len(data) or chunk_end + 4 > len(data):
            raise PerceptionError("E_PERCEPTION_SNAPSHOT_INVALID", "PNG chunk is truncated")
        chunk = bytes(view[chunk_start:chunk_end])
        expected_crc = int.from_bytes(view[chunk_end : chunk_end + 4], "big")
        if zlib.crc32(chunk_type + chunk) & 0xFFFFFFFF != expected_crc:
            raise PerceptionError("E_PERCEPTION_SNAPSHOT_INVALID", "PNG chunk checksum failed")
        if chunk_type == b"IHDR":
            if saw_ihdr or length != 13:
                raise PerceptionError("E_PERCEPTION_SNAPSHOT_INVALID", "PNG header is invalid")
            saw_ihdr = True
            width = int.from_bytes(chunk[0:4], "big")
            height = int.from_bytes(chunk[4:8], "big")
            bit_depth = chunk[8]
            color_type = chunk[9]
            interlace = chunk[12]
            if chunk[10] != 0 or chunk[11] != 0:
                raise PerceptionError("E_PERCEPTION_SNAPSHOT_INVALID", "PNG compression method is unsupported")
            if bit_depth != 8 or color_type not in _CHANNELS:
                raise PerceptionError(
                    "E_PERCEPTION_SNAPSHOT_INVALID",
                    "only 8-bit gray/palette/RGB/RGBA PNG snapshots are supported",
                )
            if interlace != 0:
                raise PerceptionError("E_PERCEPTION_SNAPSHOT_INVALID", "interlaced PNG snapshots are unsupported")
            if not min_dimension <= width <= max_dimension or not min_dimension <= height <= max_dimension:
                raise PerceptionError(
                    "E_PERCEPTION_SNAPSHOT_INVALID",
                    f"snapshot dimensions must be between {min_dimension} and {max_dimension} pixels",
                )
        elif chunk_type == b"PLTE":
            palette = chunk
        elif chunk_type == b"IDAT":
            if not saw_ihdr:
                raise PerceptionError("E_PERCEPTION_SNAPSHOT_INVALID", "PNG data precedes the header")
            idat.extend(chunk)
        elif chunk_type == b"IEND":
            saw_iend = True
            break
        offset = chunk_end + 4

    if not saw_ihdr or not saw_iend or not idat:
        raise PerceptionError("E_PERCEPTION_SNAPSHOT_INVALID", "PNG stream is incomplete")
    if color_type == 3 and (palette is None or len(palette) % 3 != 0 or not palette):
        raise PerceptionError("E_PERCEPTION_SNAPSHOT_INVALID", "palette PNG is missing its palette")

    channels = _CHANNELS[color_type]
    stride = width * channels
    expected = (stride + 1) * height
    try:
        raw = zlib.decompress(bytes(idat), bufsize=expected)
    except zlib.error as exc:
        raise PerceptionError("E_PERCEPTION_SNAPSHOT_INVALID", "PNG pixel data is corrupt") from exc
    if len(raw) != expected:
        raise PerceptionError("E_PERCEPTION_SNAPSHOT_INVALID", "PNG pixel data has the wrong length")

    grid_sums = [[0] * _GRID_COLUMNS for _ in range(_GRID_ROWS)]
    grid_counts = [[0] * _GRID_COLUMNS for _ in range(_GRID_ROWS)]
    total_luma = 0
    previous = bytearray(stride)
    for row in range(height):
        line_start = row * (stride + 1)
        filter_type = raw[line_start]
        line = bytearray(raw[line_start + 1 : line_start + 1 + stride])
        _unfilter(line, previous, filter_type, channels)
        previous = line
        grid_row = row * _GRID_ROWS // height
        row_sums = grid_sums[grid_row]
        row_counts = grid_counts[grid_row]
        for column in range(width):
            base = column * channels
            if color_type == 0 or color_type == 4:
                luma = line[base]
            elif color_type == 3:
                index = line[base] * 3
                if index + 3 > len(palette):  # type: ignore[arg-type]
                    raise PerceptionError(
                        "E_PERCEPTION_SNAPSHOT_INVALID",
                        "palette index is out of range",
                    )
                red, green, blue = palette[index : index + 3]  # type: ignore[index]
                luma = (77 * red + 150 * green + 29 * blue) >> 8
            else:
                luma = (77 * line[base] + 150 * line[base + 1] + 29 * line[base + 2]) >> 8
            total_luma += luma
            grid_column = column * _GRID_COLUMNS // width
            row_sums[grid_column] += luma
            row_counts[grid_column] += 1

    grid = tuple(
        tuple(
            (grid_sums[row][column] // grid_counts[row][column]) if grid_counts[row][column] else 0
            for column in range(_GRID_COLUMNS)
        )
        for row in range(_GRID_ROWS)
    )
    return SnapshotSummary(
        width=width,
        height=height,
        mean_luma=total_luma // (width * height),
        luma_grid=grid,
    )


def _unfilter(line: bytearray, previous: bytearray, filter_type: int, channels: int) -> None:
    if filter_type == 0:
        return
    if filter_type == 1:
        for index in range(channels, len(line)):
            line[index] = (line[index] + line[index - channels]) & 0xFF
        return
    if filter_type == 2:
        for index in range(len(line)):
            line[index] = (line[index] + previous[index]) & 0xFF
        return
    if filter_type == 3:
        for index in range(len(line)):
            left = line[index - channels] if index >= channels else 0
            line[index] = (line[index] + ((left + previous[index]) >> 1)) & 0xFF
        return
    if filter_type == 4:
        for index in range(len(line)):
            left = line[index - channels] if index >= channels else 0
            up = previous[index]
            up_left = previous[index - channels] if index >= channels else 0
            line[index] = (line[index] + _paeth(left, up, up_left)) & 0xFF
        return
    raise PerceptionError("E_PERCEPTION_SNAPSHOT_INVALID", "PNG scanline filter is invalid")


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    delta_left = abs(estimate - left)
    delta_up = abs(estimate - up)
    delta_up_left = abs(estimate - up_left)
    if delta_left <= delta_up and delta_left <= delta_up_left:
        return left
    if delta_up <= delta_up_left:
        return up
    return up_left
