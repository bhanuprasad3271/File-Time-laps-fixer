#!/usr/bin/env python3
"""
Media Date Fixer — Offline Python Engine (100% Standard Library, Zero pip dependencies)
Runs inside Android via Chaquopy.
Handles:
  1. ZArchiver-style directory listing
  2. Filename date/time parsing (WhatsApp, Pixel, Burst, date-only, etc.)
  3. Preserving existing HH:MM:SS when filename only contains a date
  4. Updating filesystem mtime + pure-Python JPEG EXIF + pure-Python MP4/MOV atoms
  5. Editing all file details (rename, date/time, EXIF metadata)
  6. Undo log creation and restoration
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import struct
from typing import Any, Optional

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".heic", ".heif", ".dng",
}

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".3gp", ".3g2", ".mkv", ".avi", ".webm",
}

MP4_ATOM_EXTENSIONS = {".mp4", ".mov", ".m4v", ".3gp", ".3g2"}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}

# Seconds between 1904-01-01 00:00:00 UTC and 1970-01-01 00:00:00 UTC
MP4_EPOCH_OFFSET = 2082844800


def _build_dt(y: int, mo: int, d: int, h: int, mi: int, s: int) -> Optional[datetime]:
    if not (1800 <= y <= 2099):
        return None
    try:
        return datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_date_from_filename(
    filename: str,
    existing_time: tuple[int, int, int],
    day_first: bool = True,
    custom_regex: str = "",
    allow_short_year: bool = False,
) -> Optional[dict[str, Any]]:
    """Parse date (and optional time) from filename; preserve existing_time if date-only."""
    stem = Path(filename).stem
    eh, em, es = existing_time

    if custom_regex.strip():
        try:
            m = re.search(custom_regex, stem)
            if m:
                gd = m.groupdict()
                y = int(gd.get("year", 0))
                mo = int(gd.get("month", 0))
                d = int(gd.get("day", 0))
                has_time = all(gd.get(k) is not None for k in ("hour", "minute"))
                h = int(gd["hour"]) if gd.get("hour") is not None else eh
                mi = int(gd["minute"]) if gd.get("minute") is not None else em
                s = int(gd["second"]) if gd.get("second") is not None else (0 if has_time else es)
                dt = _build_dt(y, mo, d, h, mi, s)
                if dt:
                    return {"dt": dt, "pattern": "Custom Regex", "has_time": has_time}
        except re.error:
            pass

    # 1. YYYYMMDD[sep]HHMMSSmmm (Pixel, Vivo, Samsung, InShot)
    m = re.search(
        r"(?<!\d)((?:18|19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"
        r"[_\-\sT.]"
        r"([01]\d|2[0-3])([0-5]\d)([0-5]\d)(\d{3})(?!\d)",
        stem,
    )
    if m:
        y, mo, d, h, mi, s, _ms = map(int, m.groups())
        dt = _build_dt(y, mo, d, h, mi, s)
        if dt:
            return {"dt": dt, "pattern": "YYYYMMDD_HHMMSSmmm", "has_time": True}

    # 2. YYYYMMDD[sep]HHMMSS (Burst, video_, Screenshot)
    m = re.search(
        r"(?<!\d)((?:18|19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"
        r"[_\-\sT.]"
        r"([01]\d|2[0-3])([0-5]\d)([0-5]\d)(?!\d)",
        stem,
    )
    if m:
        y, mo, d, h, mi, s = map(int, m.groups())
        dt = _build_dt(y, mo, d, h, mi, s)
        if dt:
            pat = "IMG_YYYYMMDD_HHMMSS_Burst" if "burst" in stem.lower() else "YYYYMMDD_HHMMSS"
            return {"dt": dt, "pattern": pat, "has_time": True}

    # 3. 14-digit continuous YYYYMMDDHHMMSS (IMG20250810142209, DJI_)
    m = re.search(
        r"(?<!\d)((?:18|19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"
        r"([01]\d|2[0-3])([0-5]\d)([0-5]\d)(?!\d)",
        stem,
    )
    if m:
        y, mo, d, h, mi, s = map(int, m.groups())
        dt = _build_dt(y, mo, d, h, mi, s)
        if dt:
            return {"dt": dt, "pattern": "YYYYMMDDHHMMSS", "has_time": True}

    # 4. ISO 8601 / Hyphenated / Dotted Date + Time (with optional Z or offset)
    m = re.search(
        r"(?<!\d)((?:18|19|20)\d{2})[-_.\s](0[1-9]|1[0-2])[-_.\s](0[1-9]|[12]\d|3[01])"
        r"[_\-\sT.]+"
        r"([01]\d|2[0-3])[-_.:]([0-5]\d)[-_.:]([0-5]\d)(?:Z|[+-]\d{2}:?\d{2})?(?!\d)",
        stem,
    )
    if m:
        y, mo, d, h, mi, s = map(int, m.groups())
        dt = _build_dt(y, mo, d, h, mi, s)
        if dt:
            return {"dt": dt, "pattern": "YYYY-MM-DD HH:MM:SS", "has_time": True}

    # 5. YYYY-MM-DD[sep]HHMMSS (Signal)
    m = re.search(
        r"(?<!\d)((?:18|19|20)\d{2})[-_.\s](0[1-9]|1[0-2])[-_.\s](0[1-9]|[12]\d|3[01])"
        r"[_\-\sT.]+"
        r"([01]\d|2[0-3])([0-5]\d)([0-5]\d)(?!\d)",
        stem,
    )
    if m:
        y, mo, d, h, mi, s = map(int, m.groups())
        dt = _build_dt(y, mo, d, h, mi, s)
        if dt:
            return {"dt": dt, "pattern": "YYYY-MM-DD HHMMSS", "has_time": True}

    # 6. WhatsApp: IMG-20260924-WA0057 / VID_20230831_WA0001
    m = re.search(
        r"(?:IMG|VID|AUD|DOC)[-_]((?:18|19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[-_]WA\d+",
        stem,
        re.IGNORECASE,
    )
    if m:
        y, mo, d = map(int, m.groups())
        dt = _build_dt(y, mo, d, eh, em, es)
        if dt:
            return {"dt": dt, "pattern": "WhatsApp (WA)", "has_time": False}

    # 7. Month-name formats: 14-May-2024, 2024_May_14_153022, May 14, 2024
    mon_pat = "|".join(sorted(MONTH_MAP.keys(), key=len, reverse=True))
    m = re.search(
        rf"(?<!\d)(0?[1-9]|[12]\d|3[01])[-_.\s]+({mon_pat})[-_.\s,]+((?:18|19|20)\d{{2}})(?!\d)",
        stem,
        re.IGNORECASE,
    )
    if m:
        d, mname, y = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        dt = _build_dt(y, MONTH_MAP[mname], d, eh, em, es)
        if dt:
            return {"dt": dt, "pattern": "Month Name (DD-Mon-YYYY)", "has_time": False}

    m = re.search(
        rf"(?<!\d)((?:18|19|20)\d{{2}})[-_.\s]+({mon_pat})[-_.\s]+(0?[1-9]|[12]\d|3[01])"
        rf"(?:[_\-\sT.]+([01]\d|2[0-3])([0-5]\d)([0-5]\d))?(?!\d)",
        stem,
        re.IGNORECASE,
    )
    if m:
        y, mname, d = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        has_time = m.group(4) is not None
        h = int(m.group(4)) if has_time else eh
        mi = int(m.group(5)) if has_time else em
        s = int(m.group(6)) if has_time else es
        dt = _build_dt(y, MONTH_MAP[mname], d, h, mi, s)
        if dt:
            return {"dt": dt, "pattern": "Month Name (YYYY-Mon-DD)", "has_time": has_time}

    m = re.search(
        rf"\b({mon_pat})[-_.\s]+(0?[1-9]|[12]\d|3[01])[,\s_-]+((?:18|19|20)\d{{2}})(?!\d)",
        stem,
        re.IGNORECASE,
    )
    if m:
        mname, d, y = m.group(1).lower(), int(m.group(2)), int(m.group(3))
        dt = _build_dt(y, MONTH_MAP[mname], d, eh, em, es)
        if dt:
            return {"dt": dt, "pattern": "Month Name (Mon DD, YYYY)", "has_time": False}

    # 8. YYYY-MM-DD / YYYY_MM_DD (Date Only)
    m = re.search(
        r"(?<!\d)((?:18|19|20)\d{2})[-_.](0[1-9]|1[0-2])[-_.](0[1-9]|[12]\d|3[01])(?!\d)",
        stem,
    )
    if m:
        y, mo, d = map(int, m.groups())
        dt = _build_dt(y, mo, d, eh, em, es)
        if dt:
            return {"dt": dt, "pattern": "YYYY-MM-DD (Date Only)", "has_time": False}

    # 9. Compact YYYYMMDD (VID_20250810.mp4)
    m = re.search(
        r"(?<!\d)((?:18|19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)",
        stem,
    )
    if m:
        y, mo, d = map(int, m.groups())
        dt = _build_dt(y, mo, d, eh, em, es)
        if dt:
            return {"dt": dt, "pattern": "YYYYMMDD (Date Only)", "has_time": False}

    # 10. DD-MM-YYYY / MM-DD-YYYY (with optional HH-MM-SS)
    m = re.search(
        r"(?<!\d)(0?[1-9]|[12]\d|3[01])[-_.](0?[1-9]|[12]\d|3[01])[-_.]((?:18|19|20)\d{2})"
        r"(?:[_\-\sT.]+([01]\d|2[0-3])[-_.:]([0-5]\d)[-_.:]([0-5]\d))?(?!\d)",
        stem,
    )
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12:
            d, mo = a, b
        elif b > 12:
            mo, d = a, b
        elif day_first:
            d, mo = a, b
        else:
            mo, d = a, b
        has_time = m.group(4) is not None
        h = int(m.group(4)) if has_time else eh
        mi = int(m.group(5)) if has_time else em
        s = int(m.group(6)) if has_time else es
        dt = _build_dt(y, mo, d, h, mi, s)
        if dt:
            return {"dt": dt, "pattern": "DD-MM-YYYY" if day_first else "MM-DD-YYYY", "has_time": has_time}

    # 11. Compact 8-digit DDMMYYYY / MMDDYYYY (no separators, e.g. IMG_14052024.jpg)
    m = re.search(
        r"(?<!\d)(0[1-9]|[12]\d|3[01])(0[1-9]|[12]\d|3[01])((?:18|19|20)\d{2})(?!\d)",
        stem,
    )
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12:
            d, mo = a, b
        elif b > 12:
            mo, d = a, b
        elif day_first:
            d, mo = a, b
        else:
            mo, d = a, b
        dt = _build_dt(y, mo, d, eh, em, es)
        if dt:
            return {"dt": dt, "pattern": "DDMMYYYY (Date Only)", "has_time": False}

    # 12. Unix Epoch Timestamp (13-digit ms or 10-digit sec, e.g. FB_IMG_1684078222123.jpg)
    m = re.search(r"(?<!\d)(1\d{9}|1\d{12})(?!\d)", stem)
    if m:
        raw = int(m.group(1))
        ts = raw / 1000.0 if len(m.group(1)) == 13 else float(raw)
        try:
            dt = datetime.fromtimestamp(ts)
            if 2000 <= dt.year <= 2099:
                return {"dt": dt, "pattern": "Unix Timestamp", "has_time": True}
        except (OSError, OverflowError, ValueError):
            pass

    # 13. Optional 6-digit short year YYMMDD[_HHMMSS] (disabled by default to avoid sequence collisions)
    if allow_short_year:
        m = re.search(
            r"(?<!\d)(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"
            r"(?:[_\-\sT.]([01]\d|2[0-3])([0-5]\d)([0-5]\d))?(?!\d)",
            stem,
        )
        if m:
            yy, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            y = 2000 + yy if yy <= 69 else 1900 + yy
            has_time = m.group(4) is not None
            h = int(m.group(4)) if has_time else eh
            mi = int(m.group(5)) if has_time else em
            s = int(m.group(6)) if has_time else es
            dt = _build_dt(y, mo, d, h, mi, s)
            if dt:
                return {"dt": dt, "pattern": "Short Year (YYMMDD)", "has_time": has_time}

    return None


def _read_jpeg_exif_fields(path: Path) -> dict[str, str]:
    """Read basic EXIF ASCII/GPS fields from a JPEG using pure Python."""
    out: dict[str, str] = {}
    try:
        raw = path.read_bytes()
        if not raw.startswith(b"\xff\xd8"):
            return out
        pos = 2
        app1 = None
        while pos + 4 <= len(raw):
            if raw[pos] != 0xFF:
                break
            marker = raw[pos + 1]
            if marker == 0xDA or marker == 0xD9:
                break
            seg_len = struct.unpack(">H", raw[pos + 2:pos + 4])[0]
            if marker == 0xE1 and raw[pos + 4:pos + 10] == b"Exif\x00\x00":
                app1 = raw[pos + 10:pos + 2 + seg_len]
                break
            pos += 2 + seg_len
        if not app1 or len(app1) < 8:
            return out

        endian = "<" if app1[:2] == b"II" else ">" if app1[:2] == b"MM" else None
        if not endian:
            return out

        ifd0_off = struct.unpack(endian + "I", app1[4:8])[0]

        def read_ifd(off: int) -> dict[int, tuple[int, int, bytes]]:
            tags: dict[int, tuple[int, int, bytes]] = {}
            if off + 2 > len(app1):
                return tags
            cnt = struct.unpack(endian + "H", app1[off:off + 2])[0]
            for i in range(cnt):
                e_off = off + 2 + i * 12
                if e_off + 12 > len(app1):
                    break
                tag, typ, num, val_off = struct.unpack(endian + "HHII", app1[e_off:e_off + 12])
                type_sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1}
                sz = type_sizes.get(typ, 1) * num
                if sz <= 4:
                    data = app1[e_off + 8:e_off + 8 + sz]
                else:
                    data = app1[val_off:val_off + sz]
                tags[tag] = (typ, num, data)
            return tags

        ifd0 = read_ifd(ifd0_off)
        tag_map = {
            0x010E: "description",
            0x010F: "make",
            0x0110: "model",
            0x0131: "software",
            0x0132: "date_time",
            0x013B: "artist",
        }
        for tid, key in tag_map.items():
            if tid in ifd0:
                out[key] = ifd0[tid][2].decode("utf-8", errors="ignore").strip("\x00 ")

        if 0x8769 in ifd0:
            exif_off = struct.unpack(endian + "I", ifd0[0x8769][2][:4].ljust(4, b"\x00"))[0]
            exif_ifd = read_ifd(exif_off)
            if 0x9003 in exif_ifd:
                out["date_time_original"] = exif_ifd[0x9003][2].decode("utf-8", errors="ignore").strip("\x00 ")
            if 0x9286 in exif_ifd:
                uc = exif_ifd[0x9286][2]
                if uc.startswith(b"ASCII\x00\x00\x00"):
                    uc = uc[8:]
                out["user_comment"] = uc.decode("utf-8", errors="ignore").strip("\x00 ")
    except Exception:
        pass
    return out


def _build_exif_app1(
    dt: datetime,
    description: str = "",
    artist: str = "",
    make: str = "",
    model: str = "",
    user_comment: str = "",
    gps_lat: Optional[float] = None,
    gps_lon: Optional[float] = None,
) -> bytes:
    """Build a valid big-endian TIFF/EXIF APP1 segment in pure Python."""
    dt_bytes = dt.strftime("%Y:%m:%d %H:%M:%S").encode("ascii") + b"\x00"

    ifd0_entries: list[tuple[int, int, int, bytes]] = []
    if description:
        b = description.encode("utf-8") + b"\x00"
        ifd0_entries.append((0x010E, 2, len(b), b))
    if make:
        b = make.encode("utf-8") + b"\x00"
        ifd0_entries.append((0x010F, 2, len(b), b))
    if model:
        b = model.encode("utf-8") + b"\x00"
        ifd0_entries.append((0x0110, 2, len(b), b))
    ifd0_entries.append((0x0132, 2, len(dt_bytes), dt_bytes))
    if artist:
        b = artist.encode("utf-8") + b"\x00"
        ifd0_entries.append((0x013B, 2, len(b), b))

    exif_entries: list[tuple[int, int, int, bytes]] = [
        (0x9003, 2, len(dt_bytes), dt_bytes),
        (0x9004, 2, len(dt_bytes), dt_bytes),
    ]
    if user_comment:
        uc = b"ASCII\x00\x00\x00" + user_comment.encode("utf-8")
        exif_entries.append((0x9286, 7, len(uc), uc))

    gps_entries: list[tuple[int, int, int, bytes]] = []
    if gps_lat is not None and gps_lon is not None:
        def pack_dms(val: float) -> bytes:
            av = abs(val)
            d = int(av)
            mf = (av - d) * 60.0
            m = int(mf)
            s = int(round((mf - m) * 60.0 * 1000))
            return struct.pack(">IIIIII", d, 1, m, 1, s, 1000)

        lat_ref = b"N\x00" if gps_lat >= 0 else b"S\x00"
        lon_ref = b"E\x00" if gps_lon >= 0 else b"W\x00"
        gps_entries.extend([
            (1, 2, 2, lat_ref),
            (2, 5, 3, pack_dms(gps_lat)),
            (3, 2, 2, lon_ref),
            (4, 5, 3, pack_dms(gps_lon)),
        ])

    # Reserve pointer tags in IFD0 for ExifIFD (0x8769) and optional GPSIFD (0x8825)
    has_gps = len(gps_entries) > 0
    ifd0_count = len(ifd0_entries) + 1 + (1 if has_gps else 0)
    ifd0_size = 2 + ifd0_count * 12 + 4
    exif_size = 2 + len(exif_entries) * 12 + 4
    gps_size = (2 + len(gps_entries) * 12 + 4) if has_gps else 0

    tiff_header = b"MM\x00\x2a" + struct.pack(">I", 8)
    data_cursor = 8 + ifd0_size + exif_size + gps_size
    extra_data = bytearray()

    def encode_ifd(entries: list[tuple[int, int, int, bytes]]) -> bytes:
        nonlocal data_cursor
        buf = bytearray(struct.pack(">H", len(entries)))
        for tag, typ, num, raw_val in sorted(entries, key=lambda x: x[0]):
            if len(raw_val) <= 4:
                buf.extend(struct.pack(">HHI", tag, typ, num))
                buf.extend(raw_val.ljust(4, b"\x00"))
            else:
                buf.extend(struct.pack(">HHII", tag, typ, num, data_cursor))
                extra_data.extend(raw_val)
                data_cursor += len(raw_val)
        buf.extend(b"\x00\x00\x00\x00")
        return bytes(buf)

    exif_ifd_offset = 8 + ifd0_size
    gps_ifd_offset = exif_ifd_offset + exif_size

    all_ifd0 = list(ifd0_entries)
    all_ifd0.append((0x8769, 4, 1, struct.pack(">I", exif_ifd_offset)))
    if has_gps:
        all_ifd0.append((0x8825, 4, 1, struct.pack(">I", gps_ifd_offset)))

    ifd0_bytes = encode_ifd(all_ifd0)
    exif_bytes = encode_ifd(exif_entries)
    gps_bytes = encode_ifd(gps_entries) if has_gps else b""

    tiff_payload = tiff_header + ifd0_bytes + exif_bytes + gps_bytes + bytes(extra_data)
    exif_segment_body = b"Exif\x00\x00" + tiff_payload
    return b"\xff\xe1" + struct.pack(">H", len(exif_segment_body) + 2) + exif_segment_body


def _write_jpeg_exif(
    path: Path,
    dt: datetime,
    description: str = "",
    artist: str = "",
    make: str = "",
    model: str = "",
    user_comment: str = "",
    gps_lat: Optional[float] = None,
    gps_lon: Optional[float] = None,
) -> tuple[bool, str]:
    """Replace or insert EXIF APP1 segment in a JPEG file using pure Python."""
    try:
        raw = path.read_bytes()
        if not raw.startswith(b"\xff\xd8"):
            return False, "Not a valid JPEG"

        existing = _read_jpeg_exif_fields(path)
        new_app1 = _build_exif_app1(
            dt=dt,
            description=description or existing.get("description", ""),
            artist=artist or existing.get("artist", ""),
            make=make or existing.get("make", ""),
            model=model or existing.get("model", ""),
            user_comment=user_comment or existing.get("user_comment", ""),
            gps_lat=gps_lat,
            gps_lon=gps_lon,
        )

        # Strip existing APP1 Exif segments, keep all other segments & image data
        out = bytearray(b"\xff\xd8")
        out.extend(new_app1)
        pos = 2
        while pos + 4 <= len(raw):
            if raw[pos] != 0xFF:
                out.extend(raw[pos:])
                break
            marker = raw[pos + 1]
            if marker == 0xDA:  # Start of Scan -> copy rest verbatim
                out.extend(raw[pos:])
                break
            if marker == 0xD9:
                out.extend(raw[pos:])
                break
            seg_len = struct.unpack(">H", raw[pos + 2:pos + 4])[0]
            if marker == 0xE1 and raw[pos + 4:pos + 10] == b"Exif\x00\x00":
                pos += 2 + seg_len
                continue
            out.extend(raw[pos:pos + 2 + seg_len])
            pos += 2 + seg_len

        path.write_bytes(bytes(out))
        return True, "EXIF updated"
    except Exception as exc:
        return False, f"EXIF error: {exc}"


def _get_existing_file_time(path: Path) -> datetime:
    if path.suffix.lower() in JPEG_EXTENSIONS:
        fields = _read_jpeg_exif_fields(path)
        for key in ("date_time_original", "date_time"):
            if key in fields:
                try:
                    return datetime.strptime(fields[key], "%Y:%m:%d %H:%M:%S")
                except ValueError:
                    pass
    return datetime.fromtimestamp(path.stat().st_mtime)


# ---------------------------------------------------------------------------
# Pure-Python MP4/MOV Creation & Modification Atom Updater
# ---------------------------------------------------------------------------
def _update_mp4_atoms(path: Path, dt: datetime) -> tuple[bool, str]:
    try:
        local_dt = dt.astimezone()
        utc_ts = int(local_dt.astimezone(timezone.utc).timestamp())
        mp4_time = max(0, utc_ts + MP4_EPOCH_OFFSET)
        file_size = path.stat().st_size
        updated_boxes = 0

        def walk_boxes(f, start: int, end: int) -> None:
            nonlocal updated_boxes
            pos = start
            while pos + 8 <= end:
                f.seek(pos)
                header = f.read(8)
                if len(header) < 8:
                    break
                size, box_type = struct.unpack(">I4s", header)
                header_len = 8
                if size == 1:
                    ext = f.read(8)
                    if len(ext) < 8:
                        break
                    size = struct.unpack(">Q", ext)[0]
                    header_len = 16
                elif size == 0:
                    size = end - pos
                if size < header_len or pos + size > end:
                    break

                content_start = pos + header_len
                if box_type in (b"moov", b"trak", b"mdia"):
                    walk_boxes(f, content_start, pos + size)
                elif box_type in (b"mvhd", b"tkhd", b"mdhd"):
                    f.seek(content_start)
                    ver_flags = f.read(4)
                    if len(ver_flags) == 4:
                        version = ver_flags[0]
                        if version == 0:
                            f.seek(content_start + 4)
                            f.write(struct.pack(">II", mp4_time & 0xFFFFFFFF, mp4_time & 0xFFFFFFFF))
                            updated_boxes += 1
                        elif version == 1:
                            f.seek(content_start + 4)
                            f.write(struct.pack(">QQ", mp4_time, mp4_time))
                            updated_boxes += 1
                pos += size

        with open(path, "r+b") as f:
            walk_boxes(f, 0, file_size)

        if updated_boxes > 0:
            return True, f"MP4 atoms updated ({updated_boxes})"
        return False, "No mvhd/tkhd/mdhd atoms found"
    except Exception as exc:
        return False, f"MP4 error: {exc}"


# ---------------------------------------------------------------------------
# Public API Called by Java via Chaquopy
# ---------------------------------------------------------------------------
def list_directory(dir_path: str) -> str:
    p = Path(dir_path)
    if not p.is_dir():
        return json.dumps({"error": f"Not a directory: {dir_path}", "entries": []})

    entries = []
    try:
        children = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except PermissionError:
        return json.dumps({"error": "Storage permission denied for this folder.", "entries": []})

    for child in children:
        try:
            st = child.stat()
            mtime_dt = datetime.fromtimestamp(st.st_mtime)
            if child.is_dir():
                try:
                    item_count = sum(1 for _ in child.iterdir())
                except Exception:
                    item_count = -1
                entries.append({
                    "name": child.name,
                    "path": str(child),
                    "is_dir": True,
                    "media_type": "DIR",
                    "size_bytes": 0,
                    "item_count": item_count,
                    "mtime_str": mtime_dt.strftime("%m/%d/%y"),
                    "mtime_full": mtime_dt.strftime("%Y-%m-%d %H:%M:%S"),
                })
            else:
                ext = child.suffix.lower()
                mtype = "IMG" if ext in IMAGE_EXTENSIONS else ("VID" if ext in VIDEO_EXTENSIONS else "FILE")
                entries.append({
                    "name": child.name,
                    "path": str(child),
                    "is_dir": False,
                    "media_type": mtype,
                    "size_bytes": st.st_size,
                    "item_count": 0,
                    "mtime_str": mtime_dt.strftime("%m/%d/%y"),
                    "mtime_full": mtime_dt.strftime("%Y-%m-%d %H:%M:%S"),
                })
        except Exception:
            continue

    return json.dumps({"path": str(p), "parent": str(p.parent), "entries": entries})


def scan_selection(selected_paths_json: str, recursive: bool = True, custom_regex: str = "", allow_short_year: bool = False) -> str:
    selected_paths = json.loads(selected_paths_json)
    collected: list[Path] = []
    seen: set[Path] = set()
    allowed = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

    for raw in selected_paths:
        p = Path(raw)
        if p.is_file() and p.suffix.lower() in allowed and p not in seen:
            collected.append(p)
            seen.add(p)
        elif p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            for child in sorted(it):
                if child.is_file() and child.suffix.lower() in allowed and child not in seen:
                    collected.append(child)
                    seen.add(child)

    items = []
    type_counts: dict[str, dict[str, Any]] = {}

    for fpath in collected:
        ext = fpath.suffix.lower()
        mtype = "Image" if ext in IMAGE_EXTENSIONS else "Video"
        existing_dt = _get_existing_file_time(fpath)
        parsed = parse_date_from_filename(
            fpath.name,
            existing_time=(existing_dt.hour, existing_dt.minute, existing_dt.second),
            custom_regex=custom_regex,
            allow_short_year=allow_short_year,
        )
        now_dt = datetime.now()
        if parsed:
            pat = parsed["pattern"]
            new_dt_str = parsed["dt"].strftime("%Y-%m-%d %H:%M:%S")
            has_time = parsed["has_time"]
            matched = True
            is_future = parsed["dt"] > now_dt
        else:
            pat = "Unmatched"
            new_dt_str = ""
            has_time = False
            matched = False
            is_future = False

        items.append({
            "path": str(fpath),
            "name": fpath.name,
            "media_type": mtype,
            "current_dt": existing_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "new_dt": new_dt_str,
            "pattern": pat,
            "has_time": has_time,
            "matched": matched,
            "is_future": is_future,
        })

        if pat not in type_counts:
            type_counts[pat] = {
                "pattern": pat,
                "count": 0,
                "sample": fpath.name,
                "has_time": has_time,
                "matched": matched,
                "has_future": False,
            }
        if is_future:
            type_counts[pat]["has_future"] = True
        type_counts[pat]["count"] += 1

    return json.dumps({
        "total": len(items),
        "types": list(type_counts.values()),
        "items": items,
    })


def apply_updates(items_json: str, undo_folder: str) -> str:
    items = json.loads(items_json)
    undo_entries = []
    results = []
    updated = 0

    for item in items:
        fpath = Path(item["path"])
        if not fpath.exists():
            results.append({"name": fpath.name, "ok": False, "detail": "File not found"})
            continue

        try:
            dt = datetime.strptime(item["new_dt"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            results.append({"name": fpath.name, "ok": False, "detail": "Invalid date format"})
            continue

        orig_mtime = fpath.stat().st_mtime
        undo_entries.append({"path": str(fpath), "original_mtime": orig_mtime})

        notes = []
        ext = fpath.suffix.lower()
        if ext in JPEG_EXTENSIONS:
            ok_meta, msg_meta = _write_jpeg_exif(fpath, dt)
            notes.append(msg_meta if ok_meta else f"EXIF skipped ({msg_meta})")
        elif ext in MP4_ATOM_EXTENSIONS:
            ok_meta, msg_meta = _update_mp4_atoms(fpath, dt)
            notes.append(msg_meta if ok_meta else f"MP4 skipped ({msg_meta})")

        try:
            ts = dt.timestamp()
            os.utime(fpath, (ts, ts))
            notes.append("mtime updated")
        except (OSError, OverflowError, ValueError):
            notes.append("mtime skipped (pre-1970 unsupported on this storage)")
        updated += 1
        results.append({"name": fpath.name, "path": str(fpath), "ok": True, "detail": "; ".join(notes)})

    undo_path = Path(undo_folder) / "_media_date_fixer_undo.json"
    try:
        undo_path.write_text(json.dumps(undo_entries, indent=2), encoding="utf-8")
        undo_str = str(undo_path)
    except Exception:
        undo_str = ""

    return json.dumps({
        "updated": updated,
        "total": len(items),
        "undo_path": undo_str,
        "results": results,
    })


def undo_last_run(undo_path_str: str) -> str:
    p = Path(undo_path_str)
    if not p.exists():
        return json.dumps({"restored": 0, "failed": 0, "error": "Undo log not found"})
    data = json.loads(p.read_text(encoding="utf-8"))
    restored = 0
    failed = 0
    for rec in data:
        fp = Path(rec["path"])
        if not fp.exists():
            failed += 1
            continue
        try:
            ts = float(rec["original_mtime"])
            os.utime(fp, (ts, ts))
            restored += 1
        except Exception:
            failed += 1
    return json.dumps({"restored": restored, "failed": failed})


def get_file_details(file_path: str) -> str:
    p = Path(file_path)
    if not p.exists():
        return json.dumps({"error": "File not found"})

    dt = _get_existing_file_time(p)
    fields = _read_jpeg_exif_fields(p) if p.suffix.lower() in JPEG_EXTENSIONS else {}
    return json.dumps({
        "path": str(p),
        "name": p.name,
        "date_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "description": fields.get("description", ""),
        "artist": fields.get("artist", ""),
        "make": fields.get("make", ""),
        "model": fields.get("model", ""),
        "user_comment": fields.get("user_comment", ""),
        "gps_lat": "",
        "gps_lon": "",
        "is_jpeg": p.suffix.lower() in JPEG_EXTENSIONS,
    })


def save_file_details(payload_json: str) -> str:
    data = json.loads(payload_json)
    p = Path(data["path"])
    if not p.exists():
        return json.dumps({"ok": False, "error": "File not found"})

    new_name = data.get("name", p.name).strip()
    if new_name and new_name != p.name:
        target = p.with_name(new_name)
        if target.exists():
            return json.dumps({"ok": False, "error": f"A file named {new_name} already exists"})
        p.rename(target)
        p = target

    raw_dt = data.get("date_time", "").strip()
    dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw_dt, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return json.dumps({"ok": False, "error": "Use format YYYY-MM-DD HH:MM:SS"})
    ext = p.suffix.lower()

    if ext in JPEG_EXTENSIONS:
        lat_v = None
        lon_v = None
        try:
            if data.get("gps_lat", "").strip() and data.get("gps_lon", "").strip():
                lat_v = float(data["gps_lat"].strip())
                lon_v = float(data["gps_lon"].strip())
        except ValueError:
            pass
        _write_jpeg_exif(
            path=p,
            dt=dt,
            description=data.get("description", ""),
            artist=data.get("artist", ""),
            make=data.get("make", ""),
            model=data.get("model", ""),
            user_comment=data.get("user_comment", ""),
            gps_lat=lat_v,
            gps_lon=lon_v,
        )
    elif ext in MP4_ATOM_EXTENSIONS:
        _update_mp4_atoms(p, dt)

    try:
        ts = dt.timestamp()
        os.utime(p, (ts, ts))
    except (OSError, OverflowError, ValueError):
        pass
    return json.dumps({"ok": True, "path": str(p), "name": p.name})


def apply_bundle_date(paths_json: str, date_time_str: str, undo_folder: str) -> str:
    """Overwrite date & time on any selected files and/or folders at once."""
    raw_dt = date_time_str.strip()
    dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw_dt, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return json.dumps({"ok": False, "error": "Use format YYYY-MM-DD HH:MM:SS"})

    paths = json.loads(paths_json)
    undo_entries = []
    results = []
    updated = 0
    media_paths = []

    for raw in paths:
        p = Path(raw)
        if not p.exists():
            results.append({"name": p.name, "ok": False, "detail": "Not found"})
            continue
        undo_entries.append({"path": str(p), "original_mtime": p.stat().st_mtime})
        notes = []
        if p.is_file():
            ext = p.suffix.lower()
            if ext in JPEG_EXTENSIONS:
                ok_m, msg_m = _write_jpeg_exif(p, dt)
                notes.append(msg_m if ok_m else f"EXIF skipped ({msg_m})")
            elif ext in MP4_ATOM_EXTENSIONS:
                ok_m, msg_m = _update_mp4_atoms(p, dt)
                notes.append(msg_m if ok_m else f"MP4 skipped ({msg_m})")
            if ext in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS):
                media_paths.append(str(p))
        try:
            ts = dt.timestamp()
            os.utime(p, (ts, ts))
            notes.append("mtime updated")
        except (OSError, OverflowError, ValueError):
            notes.append("mtime skipped (pre-1970 unsupported)")
        updated += 1
        results.append({"name": p.name, "ok": True, "detail": "; ".join(notes)})

    undo_path = Path(undo_folder) / "_media_date_fixer_undo.json"
    try:
        undo_path.write_text(json.dumps(undo_entries, indent=2), encoding="utf-8")
        undo_str = str(undo_path)
    except Exception:
        undo_str = ""

    return json.dumps({
        "ok": True,
        "updated": updated,
        "total": len(paths),
        "undo_path": undo_str,
        "media_paths": media_paths,
        "results": results,
    })
