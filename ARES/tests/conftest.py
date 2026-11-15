import os
import tempfile

# tests never touch the real local databases: everything they write goes to a throw-away data folder
os.environ.setdefault("ARES_DATA_DIR", tempfile.mkdtemp(prefix="ares-test-data-"))
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")  # single-threaded inference, set before numpy/sklearn load
