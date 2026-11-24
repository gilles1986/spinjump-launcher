"""Builds SMWPlayExtension.zip from extension/ (without tests). Usage: python build-extension.py [target folder]"""
import os
import sys
import zipfile

here = os.path.dirname(os.path.abspath(__file__))
out = os.path.join(sys.argv[1] if len(sys.argv) > 1 else here, "SMWPlayExtension.zip")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for name in ("manifest.json", "content.js"):
        z.write(os.path.join(here, "extension", name), "SMWPlayExtension/" + name)
    z.writestr(
        "SMWPlayExtension/README.txt",
        "SMW Play for SMW Central\n\nchrome://extensions -> Developer mode -> Load unpacked -> choose this folder.\n"
        "See https://spinjump.club/launcher\n",
    )
print(out)
