#!/usr/bin/env python3
"""Connector CLI driver: auth / fetch / excavate / report / audit / calibrate.

Thin dispatcher over system/connectors/. Connectors are a RARE excavation,
not a sync service: one initial full pull, then a re-run maybe quarterly or
yearly. The ledger is permanent; relevance is recomputed on every run.

Usage:
    python3 system/connector.py auth gmail
    python3 system/connector.py fetch gmail [--probe] [--limit N]
    python3 system/connector.py excavate gmail [--dry-run] [--cap N]
    python3 system/connector.py dossier gmail [--limit N] [--model M] [--redossier] [--dry-run]
    python3 system/connector.py report gmail
    python3 system/connector.py audit gmail
    python3 system/connector.py calibrate gmail [--set-threshold X]
"""

from __future__ import annotations

import argparse
import importlib

from connectors.base import DEFAULT_PROMOTION_CAP

# name → (module, class). Lazy-imported so connector modules (and their
# optional third-party SDKs) load only when that connector is used.
CONNECTORS = {
    "gmail": ("connectors.gmail", "GmailConnector"),
}


def get_connector(name: str):
    module_path, class_name = CONNECTORS[name]
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


def cmd_auth(args: argparse.Namespace) -> int:
    connector = get_connector(args.connector)
    return connector.run_auth_flow()


def cmd_fetch(args: argparse.Namespace) -> int:
    connector = get_connector(args.connector)
    if args.probe:
        connector.probe(per_window=args.per_window)
        return 0
    connector.fetch(limit=args.limit)
    return 0


def cmd_excavate(args: argparse.Namespace) -> int:
    connector = get_connector(args.connector)
    summary = connector.excavate(dry_run=args.dry_run, cap=args.cap)
    return 1 if summary.get("promotion_errors") else 0


def cmd_dossier(args: argparse.Namespace) -> int:
    connector = get_connector(args.connector)
    from connectors.dossier import run_dossier_pass
    summary = run_dossier_pass(
        connector, limit=args.limit, model=args.model,
        redossier=args.redossier, dry_run=args.dry_run)
    return 1 if summary.get("errors") else 0


def cmd_report(args: argparse.Namespace) -> int:
    return get_connector(args.connector).report()


def cmd_audit(args: argparse.Namespace) -> int:
    return get_connector(args.connector).audit()


def cmd_calibrate(args: argparse.Namespace) -> int:
    connector = get_connector(args.connector)
    if args.set_threshold is not None:
        connector.set_threshold(args.set_threshold)
        return 0
    connector.calibrate()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lifehug connector driver")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("auth", help="One-time OAuth consent (gmail.readonly only)")
    p.add_argument("connector", choices=sorted(CONNECTORS))
    p.set_defaults(func=cmd_auth)

    p = sub.add_parser("fetch", help="Append new message metadata to the permanent ledger")
    p.add_argument("connector", choices=sorted(CONNECTORS))
    p.add_argument("--probe", action="store_true",
                   help="Phase 0: stratified sample + probe report only (no ledger, no bodies)")
    p.add_argument("--per-window", type=int, default=50, help="Probe sample size per era window")
    p.add_argument("--limit", type=int, default=None, help="Max messages to list this fetch")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("excavate",
                       help="Re-score the ENTIRE ledger against the current wiki/rosters/sources; "
                            "refresh date evidence + discovery; delta-promote")
    p.add_argument("connector", choices=sorted(CONNECTORS))
    p.add_argument("--dry-run", action="store_true", help="Report what would promote; write nothing")
    p.add_argument("--cap", type=int, default=DEFAULT_PROMOTION_CAP,
                   help=f"Max threads promoted this run (default {DEFAULT_PROMOTION_CAP})")
    p.set_defaults(func=cmd_excavate)

    p = sub.add_parser("dossier",
                       help="AI correspondent dossiers (v108): classify top unclassified "
                            "correspondents from sampled thread bodies; verdicts persist and "
                            "family-class verdicts auto-apply as VIPs during scoring")
    p.add_argument("connector", choices=sorted(CONNECTORS))
    p.add_argument("--limit", type=int, default=None,
                   help="Max correspondents dossiered this run (default 30)")
    p.add_argument("--model", default=None, metavar="M",
                   help="Model override (default: config.yaml classify_model, else claude-sonnet-5)")
    p.add_argument("--redossier", action="store_true",
                   help="Re-classify even correspondents with fresh dossiers")
    p.add_argument("--dry-run", action="store_true",
                   help="Show who would be dossiered; no fetches, no AI calls, no writes")
    p.set_defaults(func=cmd_dossier)

    p = sub.add_parser("report", help="Ledger summary: volume, span, bands, threshold")
    p.add_argument("connector", choices=sorted(CONNECTORS))
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("audit", help="List auto-promoted sources with scores, newest first")
    p.add_argument("connector", choices=sorted(CONNECTORS))
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("calibrate",
                       help="Phase 2 shadow report: score distribution, per-band counts at "
                            "thresholds 0.5/0.6/0.7/0.8, random examples with reasons, "
                            "discovery preview")
    p.add_argument("connector", choices=sorted(CONNECTORS))
    p.add_argument("--set-threshold", type=float, default=None, metavar="X",
                   help="Record the chosen promote threshold in state/connectors/weights.json")
    p.set_defaults(func=cmd_calibrate)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
