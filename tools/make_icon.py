"""Write Luminary's app icon as a multi-size .ico (PNG-compressed entries) for the Start-menu shortcut."""
import struct
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402

from ui.icons import app_icon_pixmap  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png(size: int) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    app_icon_pixmap(size).save(buf, "PNG")
    return bytes(data)


def main(out: Path) -> None:
    app = QGuiApplication(sys.argv)  # painting needs a live application object
    blobs = [png(s) for s in SIZES]
    offset = 6 + 16 * len(SIZES)
    entries = b""
    for size, blob in zip(SIZES, blobs):
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(struct.pack("<HHH", 0, 1, len(SIZES)) + entries + b"".join(blobs))
    app.quit()
    print(out)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else APP / "assets" / "luminary.ico")
