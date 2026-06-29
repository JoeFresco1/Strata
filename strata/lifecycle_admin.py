from __future__ import annotations

import argparse

from strata.config import AppConfig
from strata.storage import build_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Admin-only Strata project lifecycle tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    purge = subparsers.add_parser("purge-project", help="Irreversibly remove one project and its project-scoped rows.")
    purge.add_argument("project_id")
    purge.add_argument("--confirm", help="Required token for destructive purge: PURGE-<first 8 project id characters>.")
    purge.add_argument("--dry-run", action="store_true", help="Report affected row counts and matching artifacts without deleting anything.")
    purge.add_argument("--delete-artifacts", action="store_true", help="Also remove matching files from the configured exports directory.")
    cleanup = subparsers.add_parser("cleanup-project-data", help="Apply configured or explicit retention cleanup for one project.")
    cleanup.add_argument("project_id")
    cleanup.add_argument("--telemetry-days", type=int)
    cleanup.add_argument("--telemetry-body-days", type=int)
    cleanup.add_argument("--research-days", type=int)
    cleanup.add_argument("--assistant-days", type=int)
    cleanup.add_argument("--exports-days", type=int)
    args = parser.parse_args()

    config = AppConfig()
    db = build_database(config)
    if args.command == "purge-project":
        result = db.purge_project(
            args.project_id,
            confirmation_token=args.confirm,
            delete_artifacts=args.delete_artifacts,
            exports_dir=config.exports_dir,
            dry_run=args.dry_run,
        )
        print(result)
    elif args.command == "cleanup-project-data":
        result = {
            "telemetry": db.cleanup_project_telemetry(
                args.project_id,
                retention_days=args.telemetry_days,
                body_retention_days=args.telemetry_body_days,
            ),
            "research": db.cleanup_project_research(args.project_id, retention_days=args.research_days),
            "assistant": db.cleanup_project_assistant_history(args.project_id, retention_days=args.assistant_days),
            "exports": db.cleanup_project_exports(args.project_id, exports_dir=config.exports_dir, retention_days=args.exports_days),
        }
        print(result)


if __name__ == "__main__":
    main()
