import os
import sys
import tempfile
from pathlib import Path

# Isolated data dir + demo mode before any app module is imported.
os.environ["INVESTOR_DATA"] = tempfile.mkdtemp(prefix="stockradar-test-")
os.environ["FIXTURE_MODE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
