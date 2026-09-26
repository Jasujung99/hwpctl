"""Compatibility entry point; implementation lives in hwpctl.authoring.legacy."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from hwpctl.authoring import legacy as _legacy

# Keep established imports of the example's public classes/functions working.
globals().update({name: value for name, value in vars(_legacy).items() if not name.startswith("__")})
if __name__ == "__main__":
    raise SystemExit(_legacy.main())
