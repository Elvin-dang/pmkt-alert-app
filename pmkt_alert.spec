# PyInstaller spec – one-file windowed build. CI sets APP_NAME=PMKT-Alert-vX.Y.Z.
import os

a = Analysis(
    ["src/pmkt_alert/app.py"],
    pathex=["src"],
    datas=[("src/pmkt_alert/ui", "pmkt_alert/ui")],
    hiddenimports=["webview.platforms.edgechromium", "webview.platforms.winforms", "clr"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name=os.environ.get("APP_NAME", "PMKT-Alert"),
    console=False,
    upx=False,
)
