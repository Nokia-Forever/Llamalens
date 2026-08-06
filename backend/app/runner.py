from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch llama-server from a LlamaLens active profile")
    parser.add_argument("--profile", required=True, help="Path to active-profile.json")
    args = parser.parse_args()
    payload = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    argv = payload.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
        raise SystemExit("active profile does not contain a valid argv array")
    os.execv(argv[0], argv)


if __name__ == "__main__":
    main()
