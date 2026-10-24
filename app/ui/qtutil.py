"""Qt <-> Pillow helpers, icons and small widgets."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget


class FreeAfterExec:
    """For dialogs made for one use: once closed they are freed with their pictures.
    (A dialog with a parent otherwise stays in memory until the app closes, so opening a
    preview twenty times would keep twenty copies of a big print.)
    deleteLater() is called at the caller's level, so the caller can still read the dialog
    after exec(); it goes when control is back in the main event loop."""

    def exec(self, *a, **k):
        r = super().exec(*a, **k)
        try:
            self.deleteLater()
        except RuntimeError:
            pass
        return r


def pil_to_qimage(img: Image.Image) -> QImage:
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
    if img.width * img.height > 4_000_000:
        return _pil_to_qimage_in_strips(img)
    if img.mode == "RGB":           # 3 bytes a pixel: big prints need far less memory
        data = img.tobytes("raw", "RGB")
        qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)
    else:
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
    out = qimg.copy()  # detach from the Python buffer
    del data
    return out


def small_rgb(img: Image.Image, box, resample=Image.Resampling.BICUBIC, keep_alpha: bool = False) -> Image.Image:
    """An RGB copy that fits in box (w, h), made without full-size copies first.
    (img.convert("RGB").copy() then thumbnail() needed two copies of the whole design: 1.5 GB for a
    250 MP mural, every time a thumbnail was drawn.)"""
    w, h = img.size
    k = min(box[0] / max(1, w), box[1] / max(1, h), 1.0)
    if img.mode in ("P", "1", "I", "I;16", "F", "CMYK"):      # modes resize can't filter well
        if k < 0.5:
            img = img.resize((max(1, round(w * k * 2)), max(1, round(h * k * 2))),
                             Image.Resampling.NEAREST)
        img = img.convert("RGBA" if img.mode == "P" and "transparency" in img.info else "RGB")  # keeps P alpha
        w, h = img.size
        k = min(box[0] / w, box[1] / h, 1.0)
    out = img if k >= 1 else img.resize((max(1, round(w * k)), max(1, round(h * k))), resample,
                                        reducing_gap=3.0)
    alpha = keep_alpha and ("A" in out.getbands() or "transparency" in out.info)
    return out.convert("RGBA" if alpha else "RGB")    # also a copy, so the caller may change it


def _pil_to_qimage_in_strips(img: Image.Image) -> QImage:
    """Big pictures: fill the QImage a strip at a time instead of making two full-size copies
    first (a 250 MP print needed 1.5 GB extra for a moment, enough to run an 8 GB PC out of memory)."""
    mode = img.mode
    bpp = 3 if mode == "RGB" else 4
    fmt = QImage.Format.Format_RGB888 if mode == "RGB" else QImage.Format.Format_RGBA8888
    w, h = img.size
    qimg = QImage(w, h, fmt)
    if qimg.isNull():
        raise MemoryError("not enough memory to show the picture")
    bpl = qimg.bytesPerLine()
    bits = qimg.bits()
    mv = bits if isinstance(bits, memoryview) else memoryview(bits)
    mv = mv.cast("B")
    row = w * bpp
    step = max(1, 16_000_000 // row)
    for y0 in range(0, h, step):
        y1 = min(h, y0 + step)
        chunk = img.crop((0, y0, w, y1)).tobytes("raw", mode)
        if bpl == row:
            mv[y0 * bpl:y1 * bpl] = chunk
        else:                                   # rows are padded to 4 bytes
            for k in range(y1 - y0):
                o = (y0 + k) * bpl
                mv[o:o + row] = chunk[k * row:(k + 1) * row]
    return qimg


def qimage_to_pil(qimg: QImage) -> Image.Image:
    qimg = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h, bpl = qimg.width(), qimg.height(), qimg.bytesPerLine()
    buf = bytes(qimg.constBits())[: bpl * h]
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "RGBA", bpl, 1).copy()
    if img.getchannel("A").getextrema()[0] == 255:
        img = img.convert("RGB")
    return img


# ----------------------------------------------------------------------------
# Icons (simple line icons drawn as SVG; colour is substituted at runtime)
# ----------------------------------------------------------------------------
_P = {
    "resize": '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    "crop": '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    "unlink": '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7"/><path d="M4 4l16 16"/>',
    "save": '<path d="M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v5h8V3M7 21v-7h10v7"/>',
    "copy": '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>',
    "send": '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/>',
    "chat": '<path d="M21 12a8.5 8.5 0 0 1-12.6 7.4L3 21l1.6-5.2A8.5 8.5 0 1 1 21 12z"/>',
    "reset": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    "rot_left": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    "rot_right": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    "flip_h": '<path d="M12 3v18"/><path d="M8 7L3 12l5 5z"/><path d="M16 7l5 5-5 5z"/>',
    "flip_v": '<path d="M3 12h18"/><path d="M7 8l5-5 5 5z"/><path d="M7 16l5 5 5-5z"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H9a5 5 0 0 0 0 10h3"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "fit": '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/>',
    "zoom": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3M11 8v6M8 11h6"/>',
    "batch": '<rect x="7" y="7" width="14" height="14" rx="2"/><path d="M3 15V5a2 2 0 0 1 2-2h10"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="M21 15l-5-5L5 21"/>',
    "paste": '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "help": '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01"/>',
    "sparkle": '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5M12 3v12"/>',
    # --- icons used by the editor layout (CUR = the icon colour) ---
    "home": '<path fill="CUR" stroke="CUR" stroke-width="1.5" d="M12 3.2L2.8 11h2.7v9h5v-5.5h3V20h5v-9h2.7z"/>',
    "cloud": ('<path fill="CUR" stroke="none" d="M6.6 19.5A4.6 4.6 0 0 1 5.7 10.4 6.6 6.6 0 0 1 18.4 8.6'
              ' 5.5 5.5 0 0 1 17.6 19.5z"/><path stroke="#ffffff" stroke-width="2.2" d="M12 16.8v-6.4M9 13.2l3-3 3 3"/>'),
    "folder_fill": '<path fill="CUR" stroke="CUR" stroke-width="1" d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4.2l2 2.2h8.8A1.5 1.5 0 0 1 21 8.7V18a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18z"/><path stroke="#ffffff" stroke-width="1.4" d="M3.5 10h17"/>',
    "download": '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 16v4h16v-4"/>',
    "printer": ('<path fill="CUR" stroke="CUR" stroke-width="1" d="M7 3h10v5H7z"/>'
                '<path fill="CUR" stroke="CUR" stroke-width="1" d="M4.5 8.5h15A1.5 1.5 0 0 1 21 10v6.5h-3.5V14h-11v2.5H3V10a1.5 1.5 0 0 1 1.5-1.5z"/>'
                '<path stroke="CUR" stroke-width="1.6" d="M7.2 14.8h9.6v6H7.2z"/><circle cx="17.6" cy="11.3" r=".9" fill="#ffffff" stroke="none"/>'),
    "whatsapp": ('<path d="M20.5 11.7a8.4 8.4 0 0 1-12.5 7.4L3.4 20.6l1.5-4.4a8.4 8.4 0 1 1 15.6-4.5z"/>'
                 '<path fill="CUR" stroke="none" d="M8.9 7.6c.2-.4.5-.5.8-.5h.5c.2 0 .4.1.5.4l.8 1.8c.1.2 0 .5-.1.7l-.6.7c.5 1.1 1.4 2 2.5 2.5l.7-.6c.2-.2.5-.2.7-.1l1.8.8c.3.1.4.3.4.5v.5c0 .3-.2.7-.5.8-.7.5-1.7.6-2.7.2-2-.8-3.5-2.3-4.3-4.3-.4-1-.3-2 .2-2.7z"/>'),
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M20.5 20.5l-5.2-5.2"/>',
    "zoom_out": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M20.5 20.5l-5.2-5.2M7.5 10.5h6"/>',
    "zoom_in": '<circle cx="12" cy="12" r="9.2" fill="CUR" stroke="none"/><path stroke="#ffffff" stroke-width="2.2" d="M12 7.6v8.8M7.6 12h8.8"/>',
    "fullscreen": '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
    "close": '<path d="M18 6L6 18M6 6l12 12"/>',
    "warning": ('<path fill="CUR" stroke="CUR" stroke-width="1.5" d="M12 3.2L1.9 20.3h20.2z"/>'
                '<path stroke="#ffffff" stroke-width="2.2" d="M12 9.5v5"/><circle cx="12" cy="17.4" r="1.2" fill="#ffffff" stroke="none"/>'),
    "area": ('<rect x="3.5" y="3.5" width="7" height="7" rx="1.2"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.2"/>'
             '<rect x="3.5" y="13.5" width="7" height="7" rx="1.2"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.2"/>'),
    "frame": '<path d="M7 3v14h14"/><path d="M3 7h14v14"/>',
    "file_image": ('<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/>'
                   '<path d="M14 3v5h5"/><path d="M8 17.5l2.8-3 2 2 1.4-1.5 1.8 2.5"/>'),
    "more": ('<circle cx="12" cy="5" r="1.6" fill="CUR" stroke="none"/><circle cx="12" cy="12" r="1.6" fill="CUR" stroke="none"/>'
             '<circle cx="12" cy="19" r="1.6" fill="CUR" stroke="none"/>'),
    "chev_down": '<path d="M6 9l6 6 6-6"/>',
    "chev_right": '<path d="M9 6l6 6-6 6"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    "ruler": '<path d="M3 17L17 3l4 4L7 21z"/><path d="M7 13l2 2M10 10l2 2M13 7l2 2"/>',
    "wall": ('<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M3 9.3h18M3 14.7h18M9 4v5.3M15 4v5.3'
             'M6 9.3v5.4M12 9.3v5.4M18 9.3v5.4M9 14.7V20M15 14.7V20"/>'),
    "briefcase": '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M3 12.5h18"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "palette": ('<path d="M12 3a9 9 0 1 0 0 18c1.2 0 1.8-.9 1.8-1.8 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-1 .8-1.8 1.8-1.8H17'
                'a4 4 0 0 0 4-4C21 6.6 17 3 12 3z"/><circle cx="7.5" cy="11" r="1.3" fill="CUR" stroke="none"/>'
                '<circle cx="10.5" cy="7" r="1.3" fill="CUR" stroke="none"/><circle cx="15" cy="7.5" r="1.3" fill="CUR" stroke="none"/>'),
    "sofa": ('<path d="M5 10V8a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v2"/><path d="M3 12a2 2 0 0 1 4 0v2h10v-2a2 2 0 0 1 4 0v5H3z"/>'
             '<path d="M5 17v2M19 17v2"/>'),
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16.5 9"/>',
    "doc": '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5M8.5 13h7M8.5 16.5h7M8.5 9.5h2.5"/>',
    "grid": '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
    "pattern": ('<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7.5 3v18M12 3v18M16.5 3v18" stroke-dasharray="2 2.5"/>'
                '<circle cx="9.8" cy="8" r="1.4"/><circle cx="14.3" cy="12" r="1.4"/><circle cx="9.8" cy="16" r="1.4"/>'),
    "books": '<path d="M4 4h4v16H4zM10 4h4v16h-4z"/><path d="M16.2 5.2l3.8-1 3 15.4-3.8 1z" transform="translate(-2 0)"/>',
    "play": '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M10 8l5 2.5-5 2.5z" fill="CUR"/><path d="M8 21h8M12 17v4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "compare": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 2v20"/><path d="M5.5 15l3-4 2 2.5" />',
    "seams": '<rect x="3" y="3" width="18" height="18" rx="1.5"/><path d="M9 3v18M15 3v18" stroke-dasharray="2.5 2"/>',
    "door": '<path d="M5 21V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v17"/><path d="M3 21h18"/><circle cx="15.5" cy="12" r="1" fill="CUR"/>',
    "send_print": '<path d="M7 8V3h10v5"/><rect x="3" y="8" width="18" height="9" rx="1.5"/><path d="M7 14h10v7H7z"/><path d="M17.5 11h.01"/>',
    "tag": '<path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z"/><circle cx="7.5" cy="7.5" r="1.4"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "cloud_up": '<path d="M7 18a5 5 0 0 1-.6-10 6.5 6.5 0 0 1 12.4 1.8A4.2 4.2 0 0 1 18 18"/><path d="M12 12v8M9 15l3-3 3 3"/>',
    "folder_open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v1"/><path d="M3 19l2.5-8h16L19 19z"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/><path d="M7.5 14h2M11 14h2M14.5 14h2M7.5 17.5h2M11 17.5h2"/>',
    "backup": '<path d="M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z"/><path d="M4 7v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "camera": '<path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13.5" r="3.5"/>',
    "bug": '<rect x="7" y="7" width="10" height="13" rx="5"/><path d="M12 11v9M7 12H3M21 12h-4M7 17l-3 2M17 17l3 2M8 8 5 5M16 8l3-3M9.5 7a2.5 2.5 0 0 1 5 0"/>',
    "update": '<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v5h-5"/><path d="M12 8v5l3 2"/>',
}

_icon_cache: dict = {}


def svg_pixmap(name: str, color: str = "#334155", size: int = 20) -> QPixmap:
    key = (name, color, size)
    if key in _icon_cache:
        return _icon_cache[key]
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" stroke-width="2" stroke-linecap="round" '
           f'stroke-linejoin="round">{_P[name].replace("CUR", color)}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    scale = 3  # render big for crisp icons on high-DPI screens
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    pm.setDevicePixelRatio(scale)
    _icon_cache[key] = pm
    return pm


def icon(name: str, color: str = "#334155", checked_color: str | None = None) -> QIcon:
    ic = QIcon()
    ic.addPixmap(svg_pixmap(name, color), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(svg_pixmap(name, "#94a3b8"), QIcon.Mode.Disabled, QIcon.State.Off)
    ic.addPixmap(svg_pixmap(name, checked_color or color), QIcon.Mode.Normal, QIcon.State.On)
    return ic


def resource_path(rel: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / rel


def app_icon() -> QIcon:
    p = resource_path("assets/app.png")
    if p.is_file():
        return QIcon(str(p))
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#1a73e8"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.end()
    inner = svg_pixmap("image", "#ffffff", 40)
    p = QPainter(pm)
    p.drawPixmap(12, 12, 40, 40, inner)
    p.end()
    return QIcon(pm)


class Card(QFrame):
    """White rounded panel with an optional numbered title."""

    def __init__(self, title: str = "", icon_name: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 16)
        self.lay.setSpacing(10)
        if title:
            t = QLabel(title)
            t.setObjectName("CardTitle")
            self.lay.addWidget(t)


class TwoLineButton(QPushButton):
    """Checkable tile with a bold title and a small second line (presets, modes)."""

    def __init__(self, title: str, sub: str = "", obj: str = "PresetTile", align_left: bool = False,
                 parent=None):
        super().__init__(parent)
        self.setObjectName(obj)
        self.setCheckable(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(1)
        al = (Qt.AlignmentFlag.AlignLeft if align_left else Qt.AlignmentFlag.AlignHCenter) | \
            Qt.AlignmentFlag.AlignVCenter
        self.title = QLabel(title)
        self.title.setObjectName("PresetName")
        self.sub = QLabel(sub)
        self.sub.setObjectName("PresetDims")
        self.sub.setWordWrap(align_left)
        for lab in (self.title, self.sub):
            lab.setAlignment(al)
            lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(lab)
        self.sub.setVisible(bool(sub))
        self.setMinimumHeight(lay.sizeHint().height() + 4)

    def set_sub(self, text: str) -> None:
        self.sub.setText(text)
        self.sub.setVisible(bool(text))

    def sizeHint(self) -> QSize:
        return self.layout().sizeHint().expandedTo(QSize(60, 40))


class ElidedLabel(QLabel):
    """A label that shortens long text with … instead of widening its panel."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self._full = text or ""
        super().setText(self._full)
        self.setToolTip(self._full if len(self._full) > 24 else "")
        self.update()

    def fullText(self) -> str:  # noqa: N802
        return self._full

    def minimumSizeHint(self) -> QSize:
        h = super().minimumSizeHint().height()
        return QSize(20, h)

    def paintEvent(self, ev) -> None:
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        r = self.contentsRect()
        txt = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, r.width())
        p.drawText(r, int(self.alignment()) or int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), txt)
        p.end()


def hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("Hint")
    lab.setWordWrap(True)
    return lab


def ICON_SIZE() -> QSize:
    return QSize(18, 18)


def section(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("Section")
    return lab


def spacer_widget() -> QWidget:
    w = QWidget()
    w.setFixedHeight(2)
    return w
