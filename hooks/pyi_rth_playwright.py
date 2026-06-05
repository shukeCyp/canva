import os
import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    bundle_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    browsers_dir = bundle_dir / "browsers"
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)
