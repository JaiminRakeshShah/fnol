"""Start the src package. The repository root is on the path; src is not."""

import importlib
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))
for _name in list(sys.modules):
    if _name == "fnol_desk" or _name.startswith("fnol_desk."):
        del sys.modules[_name]
importlib.invalidate_caches()

from fnol_desk.server import main

if __name__ == "__main__":
    raise SystemExit(main())
