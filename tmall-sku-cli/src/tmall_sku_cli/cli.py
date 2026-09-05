from __future__ import annotations

import argparse
import sys

from .lark_cli import LarkCli, LarkCommandError
from .output import CliError, failure, success
from .sheet_model import SheetConfig
from .webbridge import WebBridgeClient
from .workflow import run_extract, run_write, status


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    lark = LarkCli()
    webbridge = WebBridgeClient(session=getattr(args, "session", "tmall-sku-cli"))
    try:
        if args.command == "status":
            return success(status(lark, webbridge))
        if args.command == "extract":
            config = config_from_args(args)
            return success(run_extract(args.url, config, lark, webbridge))
        if args.command == "run":
            config = config_from_args(args)
            return success(
                run_write(
                    args.url,
                    config,
                    lark,
                    webbridge,
                    force_copy=args.force_copy,
                    dry_run=args.dry_run,
                )
            )
        return failure("unknown_command", f"Unknown command: {args.command}")
    except CliError as exc:
        return failure(exc.code, exc.message, exc.details)
    except LarkCommandError as exc:
        return failure(
            "lark_cli_failed",
            "lark-cli command failed",
            {
                "command": list(exc.command),
                "returncode": exc.returncode,
                "stdout": exc.stdout,
                "stderr": exc.stderr,
            },
        )
    except KeyboardInterrupt:
        return failure("interrupted", "Interrupted by user")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tmall-sku-cli",
        description="Extract Tmall SKU prices from Feishu sheets using OpenBridge.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Check lark-cli and OpenBridge")
    status_parser.add_argument("--session", default="tmall-sku-cli")

    extract_parser = subparsers.add_parser("extract", help="Extract SKU prices without writing")
    add_common_args(extract_parser)

    run_parser = subparsers.add_parser("run", help="Extract SKU prices and write to Feishu")
    add_common_args(run_parser)
    run_parser.add_argument(
        "--force-copy", action="store_true", help="Always create a copy instead of writing original"
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract and show planned write values without writing",
    )
    return parser


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", required=True, help="Feishu wiki or sheet URL")
    parser.add_argument(
        "--url-col", default="G", help="Column containing product links, default: G"
    )
    parser.add_argument("--header-row", type=int, default=7, help="Output header row, default: 7")
    parser.add_argument("--start-row", type=int, default=8, help="First product row, default: 8")
    parser.add_argument("--max-row", type=int, default=500, help="Max row to scan, default: 500")
    parser.add_argument("--session", default="tmall-sku-cli", help="OpenBridge session name")


def config_from_args(args: argparse.Namespace) -> SheetConfig:
    return SheetConfig(
        url_col=args.url_col,
        header_row=args.header_row,
        start_row=args.start_row,
        max_row=args.max_row,
    )


if __name__ == "__main__":
    sys.exit(main())
