"""Add scripts/ to sys.path so tests can import the gate modules.

scripts/ is treated as a separate, src-isolated package per ARCHITECTURE.md
§16.9.9 (gate scripts must not import from src/stronghold).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
