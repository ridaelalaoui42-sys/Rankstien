"""Compatibility wrapper for the production multidomain startup runner."""

from __future__ import annotations

import argparse

from rankstein.startup import StartupOptions, print_startup_report, run_startup


def main() -> None:
    parser = argparse.ArgumentParser(description="RankStein multidomain worker launcher")
    parser.add_argument("--domain", action="append", dest="domains", help="Domain handle to include")
    parser.add_argument("--workers", type=int, default=2, help="Workers per selected domain")
    parser.add_argument("--keywords", type=int, default=3, help="Pending keywords to seed per domain")
    parser.add_argument("--no-launch", action="store_true", help="Audit and seed only")
    parser.add_argument("--json", action="store_true", help="Print machine-readable startup report")
    args = parser.parse_args()

    report = run_startup(
        StartupOptions(
            domains=args.domains,
            keywords_per_domain=args.keywords,
            workers_per_domain=args.workers,
            launch=not args.no_launch,
            json_output=args.json,
        )
    )
    print_startup_report(report, as_json=args.json)


if __name__ == "__main__":
    main()
