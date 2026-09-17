#!/usr/bin/env python3
"""Visible application launcher; legacy command-line collectors remain separate."""

from activity_app.__main__ import entrypoint

if __name__ == "__main__":
    raise SystemExit(entrypoint())
