#!/usr/bin/env python3
"""CLI wrapper for send_followups_sequence.py"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

from send_followups_sequence import main  # noqa: E402

if __name__ == "__main__":
    main()
