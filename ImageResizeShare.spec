# PyInstaller build recipe:  pyinstaller --noconfirm ImageResizeShare.spec
import os
from PyInstaller.utils.hooks import collect_submodules

# assets: icons, fonts, ICC colour profiles (assets/icc) and the detection models (assets/models)

datas = [("assets", "assets")]
if os.path.isfile(os.path.join("vendor", "realesrgan", "realesrgan-ncnn-vulkan.exe")):
    datas.append((os.path.join("vendor", "realesrgan"), "realesrgan"))

a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=collect_submodules("pillow_heif") + collect_submodules("qrcode") + ["PIL.ImageCms", "PySide6.QtNetwork"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia",
              "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ImageResizeShare",
    icon="assets/app.ico",
    console=False,
    upx=False,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ImageResizeShare", upx=False)
