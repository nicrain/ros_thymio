#!/usr/bin/env python3
"""Deprecated entrypoint kept for compatibility after Phase-2 refactor."""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deprecated. Use ros2 launch thymio_control <eeg_thymio|gaze_thymio|experiment_core>.launch.py"
    )
    parser.add_argument(
        "--print-replacement",
        action="store_true",
        help="Print migration commands and exit with code 0.",
    )
    args = parser.parse_args()

    lines = [
        "[DEPRECATED] scripts/thymio_ros.py has been downgraded in Phase-2 refactor.",
        "Use ROS2 launch orchestration instead:",
        "  EEG flow:  ros2 launch thymio_control eeg_thymio.launch.py",
        "  Gaze flow: ros2 launch thymio_control gaze_thymio.launch.py",
        "  Unified:    ros2 launch thymio_control experiment_core.launch.py run_eeg:=true run_gaze:=true",
    ]
    print("\n".join(lines))
    return 0 if args.print_replacement else 2


if __name__ == "__main__":
    sys.exit(main())
