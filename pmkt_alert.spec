# PyInstaller spec – one-file windowed build → dist/PMKT-Alert.exe (version lives inside the app, not the name).
import os

a = Analysis(
    ["src/pmkt_alert/app.py"],
    pathex=["src"],
    datas=[("src/pmkt_alert/ui", "pmkt_alert/ui"), ("CHANGELOG.md", "pmkt_alert")]
    + ([("src/pmkt_alert/team.json", "pmkt_alert")] if os.path.exists("src/pmkt_alert/team.json") else []),
    hiddenimports=["webview.platforms.edgechromium", "webview.platforms.winforms", "clr"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name=os.environ.get("APP_NAME", "PMKT-Alert"),
    console=False,
    icon="assets/icon.ico",
    upx=False,
)
