"""Stage one shared launcher in platform packages; WGT is unsigned for TV-side re-signing."""
from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
ICON = ROOT.parent / "app/frontend/public/brand/app-icon.png"
WORDMARK = ROOT.parent / "app/frontend/public/brand/wordmark.png"


def stage(platform: str) -> Path:
    target = DIST / platform / "app"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in ("index.html", "shell.js", "shell.css"):
        shutil.copy2(ROOT / "shared" / name, target / name)
    shutil.copy2(ICON, target / "icon.png")
    shutil.copy2(WORDMARK, target / "wordmark.png")
    document = (target / "index.html").read_text()
    document = document.replace('<script src="shell.js"></script>',
        f'<script>window.ORBIS_TV_PLATFORM = "{platform}";</script>\n  <script src="shell.js"></script>')
    (target / "index.html").write_text(document)
    if platform == "webos":
        shutil.copy2(ROOT / "webos/appinfo.json", target / "appinfo.json")
        data = json.loads((target / "appinfo.json").read_text())
        assert data["version"] == "1.0.0" and data["main"] == "index.html"
    else:
        shutil.copy2(ROOT / "tizen/config.xml", target / "config.xml")
        config = ET.parse(target / "config.xml").getroot()
        assert config.attrib["version"] == "1.0.0"
    return target


def build_wgt(target: Path) -> Path:
    package = DIST / "orbis-tizen-1.0.0.wgt"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(target.iterdir()):
            assert file.name not in {"author-signature.xml", "signature1.xml"}
            archive.write(file, file.name)
    return package


if __name__ == "__main__":
    stage("webos")
    print(build_wgt(stage("tizen")))
    print("webOS staged in tv/dist/webos/app; run tv/build-webos.sh for the official IPK")
