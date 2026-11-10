#!/usr/bin/env python3
"""
Motor Dyno Test Bench - Terminal User Interface (TUI) Launcher.

Runs a pure-Python, zero-graphical-dependency curses interface for dynamometer
monitoring and control. Works over SSH, Raspberry Pi, and headless Linux terminals.
"""

import argparse
import sys
from pathlib import Path

from modules.tui import DynoTUI


def parse_args(args=None):
    parser = argparse.ArgumentParser(
        description="Motor Dyno Test Bench - Terminal User Interface (TUI)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--port",
        type=str,
        default="",
        help="Serial port device name (e.g. /dev/ttyUSB0, COM3)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=115200,
        help="Serial communication baudrate",
    )
    parser.add_argument(
        "--demo",
        "--mock",
        dest="demo",
        action="store_true",
        help="Run in demonstration/simulation mode with simulated motor physics and auto-ack",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="Path to CSV load profile to start or stage on launch",
    )
    return parser.parse_args(args)


def main():
    args = parse_args()
    tui = DynoTUI(
        port=args.port,
        baud=args.baud,
        demo_mode=args.demo,
        initial_profile=args.profile,
    )
    try:
        tui.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
