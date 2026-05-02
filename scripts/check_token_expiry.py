#!/usr/bin/env python
"""Check how many days remain on the LinkedIn access token.

Usage:
    python scripts/check_token_expiry.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    access_token = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    expires_at_str = os.getenv("LINKEDIN_TOKEN_EXPIRES_AT", "")

    if not access_token:
        print("WARNING: LINKEDIN_ACCESS_TOKEN is not set — run linkedin_first_auth.py first.")
        sys.exit(1)

    print(f"Access token:  {access_token[:20]}…")

    if not expires_at_str:
        print("INFO: LINKEDIN_TOKEN_EXPIRES_AT not set — cannot determine expiry.")
        return

    expires_at = float(expires_at_str)
    days_remaining = (expires_at - time.time()) / 86_400

    if days_remaining < 0:
        print(f"ERROR:   Token expired {abs(days_remaining):.1f} days ago — re-authorize now.")
        sys.exit(2)
    elif days_remaining < 7:
        print(f"CRITICAL: Token expires in {days_remaining:.1f} days — refresh immediately.")
        sys.exit(2)
    elif days_remaining < 14:
        print(f"WARNING:  Token expires in {days_remaining:.1f} days — refresh soon.")
    else:
        print(f"OK:       Token expires in {days_remaining:.1f} days.")


if __name__ == "__main__":
    main()
