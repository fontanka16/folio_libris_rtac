#!/usr/bin/env python3
"""Issue (or rotate) a per-sigel fast-track token.

Generates a random token, writes it into ``libraries/<sigel>/settings.json`` as
``fast_track_token``, and prints the status URL to register for the library in
Biblioteksdatabasen. A request whose ``?token=`` matches that value is exempt
from the rtac endpoint's rate limit (see application.py).

Usage:
    python scripts/issue_token.py <sigel>
    python scripts/issue_token.py <sigel> --base-url https://rtac.bibliotekarien.se

Honours the LIBRARIES_PATH environment variable, like the app itself.
"""
import argparse
import json
import os
import secrets
import sys

LIBRARIES_DIR = os.environ.get("LIBRARIES_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "libraries"
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Issue a fast-track token for a library sigel."
    )
    parser.add_argument("sigel", help="The library sigel (a libraries/<sigel>/ dir).")
    parser.add_argument(
        "--base-url",
        default="https://rtac.bibliotekarien.se",
        help="Service base URL, used only for the printed registration URL.",
    )
    args = parser.parse_args(argv)

    settings_path = os.path.join(LIBRARIES_DIR, args.sigel, "settings.json")
    if not os.path.isfile(settings_path):
        sys.exit(
            "No settings file at {} — create it first "
            "(copy example.settings.json).".format(settings_path)
        )

    with open(settings_path, encoding="utf-8") as f:
        settings = json.load(f)

    token = secrets.token_urlsafe(32)
    settings["fast_track_token"] = token
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4, ensure_ascii=False)
        f.write("\n")

    base = args.base_url.rstrip("/")
    print("Wrote fast_track_token to {}".format(settings_path))
    print()
    print("Register this status URL for sigel '{}' in Biblioteksdatabasen:".format(
        args.sigel
    ))
    print("  {}/{}/rtac?token={}".format(base, args.sigel, token))


if __name__ == "__main__":
    main()
