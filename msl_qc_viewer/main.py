from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from msl_qc_viewer.ui.app import main
else:
    from .ui.app import main


if __name__ == "__main__":
    main()
