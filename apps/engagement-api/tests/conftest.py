"""Pytest configuration for Engagement API tests."""
from __future__ import annotations

import os
import sys

os.environ["ENVIRONMENT"] = "test"
os.environ["ENGAGEMENT_INTERNAL_TOKEN"] = "test_token"
os.environ["VIETNAMFB_API_KEY"] = "test_key"
os.environ["VIETNAMFB_BASE_URL"] = "https://vietnamfb.invalid"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
