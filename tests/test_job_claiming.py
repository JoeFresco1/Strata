from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from strata.db import Database
from strata.jobs import PlatformJobService


class JobClaimingTests(unittest.TestCase):
    """Protect database isolation and exactly-once job dispatch claims."""

    def test_importing_api_does_not_construct_database_services(self) -> None:
        """A library import must not connect to the configured database target."""
        repository = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["STRATA_DATABASE_URL"] = (
            "postgresql://invalid:invalid@127.0.0.1:1/import-must-not-connect"
        )
        completed = subprocess.run(
            [sys.executable, "-c", "import strata.api; print('safe-import')"],
            cwd=repository,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "safe-import")

    def test_two_service_instances_dispatch_one_queued_job_once(self) -> None:
        """A database compare-and-set allows only one process-local worker to win."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "job-claim.sqlite3")
            project = db.create_project("Atomic job claim", "Prevent duplicate inference.")
            job = db.create_platform_job(
                project_id=project.id,
                kind="generation",
                workflow="test_atomic_claim",
                scope="test",
            )
            services = SimpleNamespace(db=db)
            workers = [PlatformJobService(services), PlatformJobService(services)]
            dispatches: list[str] = []
            dispatch_lock = threading.Lock()
            start = threading.Barrier(3)

            def dispatch(claimed: object) -> dict[str, object]:
                with dispatch_lock:
                    dispatches.append(str(getattr(claimed, "id")))
                time.sleep(0.05)
                return {"claimed": True}

            for worker in workers:
                worker._dispatch = dispatch  # type: ignore[method-assign]

            threads = [
                threading.Thread(
                    target=lambda worker=worker: (start.wait(), worker.run_job(job.id)),
                    daemon=True,
                )
                for worker in workers
            ]
            for thread in threads:
                thread.start()
            start.wait()
            for thread in threads:
                thread.join(timeout=5)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(dispatches, [job.id])
            completed = db.get_platform_job(job.id)
            self.assertEqual(completed.status, "completed")
            self.assertEqual(completed.result_payload, {"claimed": True})

    def test_cancel_does_not_overwrite_a_concurrent_running_claim(self) -> None:
        """Queued cancellation must fall through to a running cancellation request."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "job-cancel.sqlite3")
            project = db.create_project("Atomic cancellation", "Preserve a winning claim.")
            job = db.create_platform_job(
                project_id=project.id,
                kind="generation",
                workflow="test_atomic_cancel",
                scope="test",
            )
            claimed = db.claim_platform_job(job.id)
            self.assertIsNotNone(claimed)

            cancelled = db.request_platform_job_cancel(job.id)

            self.assertEqual(cancelled.status, "running")
            self.assertTrue(cancelled.cancel_requested)
            self.assertEqual(cancelled.current_step, "Cancellation requested")


if __name__ == "__main__":
    unittest.main()
