"""
main.py — Robot entry point.

Run with:
    python main.py
    python main.py --config config.yaml   (once YAML loading is implemented)

This file is intentionally thin. It only:
  1. Configures logging.
  2. Loads configuration.
  3. Creates the RobotRuntime.
  4. Calls runtime.run() via asyncio.

All wiring is handled inside RobotRuntime.__init__().
"""

import argparse
import asyncio
import sys

from config import RobotConfig
from runtime import RobotRuntime
from utils.logger import configure_logging, get_logger


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Companion Robot Runtime",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to a YAML configuration file. Uses defaults if omitted.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity level.",
    )
    return parser.parse_args()


def load_config(args: argparse.Namespace) -> RobotConfig:
    """
    Load and return the robot configuration.

    Args:
        args: Parsed CLI arguments.

    Returns:
        A RobotConfig instance.
    """
    if args.config:
        # TODO: Enable once RobotConfig.from_yaml() is implemented.
        # return RobotConfig.from_yaml(args.config)
        print(f"WARNING: YAML config loading not yet implemented. Using defaults.")

    # Override log level from CLI if provided.
    config = RobotConfig()
    config.runtime.log_level = args.log_level
    return config


def main() -> None:
    """Robot program entry point."""
    args = parse_args()

    # Configure logging first so all subsequent imports can log.
    configure_logging(level=args.log_level)
    log = get_logger(__name__)

    log.info("=" * 60)
    log.info("Companion Robot Starting Up")
    log.info("=" * 60)

    config = load_config(args)
    runtime = RobotRuntime(config)

    try:
        asyncio.run(runtime.run())
    except KeyboardInterrupt:
        # Ctrl+C triggers the signal handler in runtime, which sets the
        # shutdown event. asyncio.run() will finish cleanly.
        pass
    except Exception as exc:
        log.critical("Fatal error in robot runtime: %s", exc, exc_info=True)
        sys.exit(1)

    log.info("Robot stopped. Goodbye.")


if __name__ == "__main__":
    main()
