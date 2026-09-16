import os

# ReportLab reads RL_invariant at import time; canvases are also created with invariant=1.
os.environ.setdefault("RL_invariant", "1")

from app.demo_gen.generate import main  # noqa: E402

raise SystemExit(main())
