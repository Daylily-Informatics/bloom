#!/usr/bin/env python3
"""
BLOOM LIMS Command Line Interface

This module redirects to the new Click-based CLI in bloom_lims.cli package.

Usage:
    bloom --help              Show all available commands
    bloom db status           Show database status
    bloom db migrate          Run database migrations
    bloom db seed             Load seed data
    bloom gui                 Start the BLOOM web UI
    bloom config              Show current configuration
    bloom info                Show environment info
    bloom doctor              Check environment health
"""

import sys

# Redirect to the new CLI module
from bloom_lims.cli import main

if __name__ == "__main__":
    sys.exit(main())

