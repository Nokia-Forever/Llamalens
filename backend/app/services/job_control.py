from __future__ import annotations

import threading


# Both operations target the same llama-server process. Serializing them keeps
# benchmark results attributable to the Profile snapshot recorded for the job.
EXECUTION_LOCK = threading.Lock()
