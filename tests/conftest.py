import sys
from pathlib import Path

# Ensure project root is importable regardless of how pytest is invoked.
# The root contains src/ as a package, enabling "from src.collectors import ..."
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)
