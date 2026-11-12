"""Scanned pages to files: PDF built from JPEG pages, PNG converted from JPEG.

The PDF is written here rather than asked from the scanner, so that pages scanned one at a time
on the glass can be added to it: each page is the scanner's JPEG embedded as is (no new
compression), and a PDF written here can be read back into its pages to add more.
"""

from __future__ import annotations

import io
import re

# A page: its JPEG, and its size in points (1/72 inch).
Page = tuple[bytes, float, float]

_SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
_COLOR_SPACES = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}
_PRODUCER = b"%HP-Printer-Scan"


class DocumentError(ValueError):
    """A page or a document could not be read."""


def jpeg_size(jpeg: bytes) -> tuple[int, int, int]:
    """Return the width, height and number of components of a JPEG."""
    if jpeg[:2] != b"\xff\xd8":
        raise DocumentError("not a JPEG")
    index = 2
    while index + 4 <= len(jpeg):
        if jpeg[index] != 0xFF:
            index += 1
            continue
        marker = jpeg[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        length = int.from_bytes(jpeg[index + 2 : index + 4], "big")
        if marker in _SOF_MARKERS and index + 10 <= len(jpeg):
            height = int.from_bytes(jpeg[index + 5 : index + 7], "big")
            width = int.from_bytes(jpeg[index + 7 : index + 9], "big")
            return width, height, jpeg[index + 9]
        index += 2 + length
    raise DocumentError("JPEG without frame header")


def page_from_jpeg(jpeg: bytes, resolution: int) -> Page:
    """A page of the size the scanner gave it at this resolution."""
    width, height, _ = jpeg_size(jpeg)
    return jpeg, width * 72 / resolution, height * 72 / resolution


def build_pdf(pages: list[Page]) -> bytes:
    """Write a PDF with one page per JPEG, each filling its page."""
    if not pages:
        raise DocumentError("no page")
    objects: list[bytes] = []
    kids: list[int] = []
    # Objects 1 and 2: catalog and page tree; then, per page: image, content, page.
    for index, (jpeg, width_pt, height_pt) in enumerate(pages):
        width, height, components = jpeg_size(jpeg)
        color_space = _COLOR_SPACES.get(components, "/DeviceRGB")
        decode = " /Decode [1 0 1 0 1 0 1 0]" if components == 4 else ""
        image = 3 + index * 3
        content = f"q {width_pt:.2f} 0 0 {height_pt:.2f} 0 0 cm /Im0 Do Q".encode()
        objects.append(
            f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace {color_space}"
            f" /BitsPerComponent 8 /Filter /DCTDecode{decode} /Length {len(jpeg)} >>\nstream\n".encode()
            + jpeg
            + b"\nendstream"
        )
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width_pt:.2f} {height_pt:.2f}]"
            f" /Resources << /XObject << /Im0 {image} 0 R >> >> /Contents {image + 1} 0 R >>".encode()
        )
        kids.append(image + 2)
    head = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{kid} 0 R' for kid in kids)}] /Count {len(kids)} >>".encode(),
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n" + _PRODUCER + b"\n")
    offsets = []
    for number, body in enumerate(head + objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(offsets) + 1}\n0000000000 65535 f \n".encode())
    out.write(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets))
    out.write(f"trailer\n<< /Size {len(offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


_IMAGE = re.compile(rb"/Subtype /Image /Width \d+ /Height \d+ .*?/Length (\d+) >>\nstream\n", re.DOTALL)
_MEDIA_BOX = re.compile(rb"/Type /Page /Parent 2 0 R /MediaBox \[0 0 ([\d.]+) ([\d.]+)\]")


def read_pdf(pdf: bytes) -> list[Page] | None:
    """Return the pages of a PDF written by build_pdf, or None for any other PDF."""
    if _PRODUCER not in pdf[:64]:
        return None
    pages: list[Page] = []
    position = 0
    # Read in order, jumping over each JPEG: its bytes are never searched for PDF syntax.
    while (image := _IMAGE.search(pdf, position)) is not None:
        start = image.end()
        end = start + int(image.group(1))
        box = _MEDIA_BOX.search(pdf, end)
        if box is None:
            return None
        pages.append((pdf[start:end], float(box.group(1)), float(box.group(2))))
        position = box.end()
    return pages or None


def jpeg_to_png(jpeg: bytes) -> bytes:
    """Convert a JPEG to PNG with Pillow, which Home Assistant ships (run it in the executor)."""
    from PIL import Image  # noqa: PLC0415 - only loaded for a PNG scan

    with Image.open(io.BytesIO(jpeg)) as image:
        out = io.BytesIO()
        image.save(out, format="PNG", optimize=True)
        return out.getvalue()
