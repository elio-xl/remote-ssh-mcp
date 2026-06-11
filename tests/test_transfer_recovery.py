from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.remote.audit_store import AuditStore
from backend.remote.transfer_store import RUNNING_STALE_SECONDS, TransferStore
from backend.remote.transfer_worker import TransferWorker


class TransferRecoveryTests(unittest.TestCase):
    def test_stale_running_transfer_releases_active_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TransferStore(Path(tmp) / "transfers.json")
            with patch("backend.remote.transfer_store.time.time", return_value=100.0):
                record = store.create_upload(
                    target_alias="prod",
                    plan_id="plan-1",
                    step_id="step-1",
                    actor="test",
                    local_path="/tmp/a",
                    local_path_display="a",
                    remote_path="/tmp/a",
                    actual_remote_path="/tmp/a",
                    temp_remote_path="/tmp/a.tmp",
                    conflict_policy="fail",
                    atomic=True,
                    verify=True,
                    bytes_total=1,
                )
                store.mark_status(record.transfer_id, "running")

            with patch(
                "backend.remote.transfer_store.time.time",
                return_value=101.0 + RUNNING_STALE_SECONDS,
            ):
                total, by_target = store.active_counts()

            final = store.get(record.transfer_id)
            self.assertIsNotNone(final)
            self.assertEqual(final.status, "timed_out")
            self.assertEqual(total, 0)
            self.assertEqual(by_target, {})

    def test_cancel_transfer_closes_active_connection(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.closed = False

            def close(self) -> None:
                self.closed = True

        class Conn:
            def __init__(self) -> None:
                self.client = Client()
                self.aux_clients: list[Client] = []

        with tempfile.TemporaryDirectory() as tmp:
            worker = TransferWorker(
                transfer_store=TransferStore(Path(tmp) / "transfers.json"),
                audit_store=AuditStore(Path(tmp) / "audit.jsonl"),
                pool=None,
            )
            conn = Conn()
            worker._register_active_connection("transfer-1", conn)

            self.assertTrue(worker.cancel_transfer("transfer-1"))
            self.assertTrue(conn.client.closed)


if __name__ == "__main__":
    unittest.main()
