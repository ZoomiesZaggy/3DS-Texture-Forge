"""Shared pytest configuration for 3DS Texture Forge tests."""

import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pytest_addoption(parser):
    parser.addoption("--rom-dir", action="store", default=None,
                     help="Directory containing 3DS ROM files")
    parser.addoption("--update-baselines", action="store_true", default=False,
                     help="Update tests/baselines.json with current counts")
