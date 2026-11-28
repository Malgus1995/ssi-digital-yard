"""Convenience entry point; no installation or third-party packages required."""
import importlib
import sys
from pathlib import Path

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
    importlib.import_module('ssi_yard.planners.meta-heuristics.run').main()
