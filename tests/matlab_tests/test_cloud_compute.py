"""
Port of MATLAB ndi.unittest.cloud.compute.* tests.

MATLAB source files:
  +cloud/+compute/ComputeTest.m  → TestCompute
  +cloud/+compute/ZombieTest.m   → TestZombie

Dual-mode tests:
  - Mocked (default): Run with no credentials using unittest.mock
  - Live API: When NDI_CLOUD_USERNAME / NDI_CLOUD_PASSWORD are set
"""

import os
import time
from unittest.mock import MagicMock

import pytest

from .conftest import requires_cloud

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _have_cloud_creds() -> bool:
    return bool(os.environ.get("NDI_CLOUD_USERNAME"))


def _login():
    from ndi.cloud.auth import login
    from ndi.cloud.client import CloudClient

    config = login(
        email=os.environ["NDI_CLOUD_USERNAME"],
        password=os.environ["NDI_CLOUD_PASSWORD"],
    )
    client = CloudClient(config)
    return config, client


# ===========================================================================
# TestCompute — Port of ComputeTest.m
# ===========================================================================


class TestCompute:
    """Port of ndi.unittest.cloud.compute.ComputeTest"""

    # ---- Mocked tests ----

    def test_startSession_mocked(self):
        """startSession returns a session ID (mocked)."""
        from ndi.cloud.api.compute import startSession

        client = MagicMock()
        client.post.return_value = {"sessionId": "session-abc-123"}

        result = startSession("hello-world-v1", client=client)
        assert result["sessionId"] == "session-abc-123"
        client.post.assert_called_once()

    def test_getSessionStatus_mocked(self):
        """getSessionStatus returns status dict (mocked)."""
        from ndi.cloud.api.compute import getSessionStatus

        client = MagicMock()
        client.get.return_value = {
            "sessionId": "session-abc-123",
            "status": "RUNNING",
            "currentStageId": "stage-1",
        }

        result = getSessionStatus("session-abc-123", client=client)
        assert result["status"] == "RUNNING"
        assert result["currentStageId"] == "stage-1"

    def test_listSessions_mocked(self):
        """listSessions returns a list of sessions (mocked)."""
        from ndi.cloud.api.compute import listSessions

        client = MagicMock()
        client.get.return_value = {
            "sessions": [
                {"sessionId": "session-1", "status": "RUNNING"},
                {"sessionId": "session-2", "status": "COMPLETED"},
            ]
        }

        result = listSessions(client=client)
        sessions = result.data
        assert isinstance(sessions, list)
        assert len(sessions) == 2
        assert sessions[0]["sessionId"] == "session-1"

    def test_listSessions_as_list_mocked(self):
        """listSessions handles direct list return (mocked)."""
        from ndi.cloud.api.compute import listSessions

        client = MagicMock()
        client.get.return_value = [
            {"sessionId": "session-1", "status": "RUNNING"},
        ]

        result = listSessions(client=client)
        sessions = result.data
        assert isinstance(sessions, list)
        assert len(sessions) == 1

    def test_abortSession_mocked(self):
        """abortSession returns True (mocked)."""
        from ndi.cloud.api.compute import abortSession

        client = MagicMock()
        client.post.return_value = {}

        result = abortSession("session-abc-123", client=client)
        assert result is True
        client.post.assert_called_once()

    def test_triggerStage_mocked(self):
        """triggerStage calls the correct endpoint (mocked)."""
        from ndi.cloud.api.compute import triggerStage

        client = MagicMock()
        client.post.return_value = {"status": "triggered"}

        result = triggerStage("session-abc-123", "stage-1", client=client)
        assert result["status"] == "triggered"

    def test_finalizeSession_mocked(self):
        """finalizeSession calls the correct endpoint (mocked)."""
        from ndi.cloud.api.compute import finalizeSession

        client = MagicMock()
        client.post.return_value = {"status": "finalized"}

        result = finalizeSession("session-abc-123", client=client)
        assert result["status"] == "finalized"

    # ---- Live tests ----

    @requires_cloud
    def test_hello_world_flow_live(self):
        """Port of ComputeTest.testHelloWorldFlow — full pipeline flow.

        1. Start 'hello-world-v1' session
        2. Check status
        3. List sessions (verify new session in list)
        4. Abort session (cleanup)
        5. triggerStage (expect possible error, just verify no crash)
        6. finalizeSession (expect possible error, just verify no crash)
        """
        from ndi.cloud.api.compute import (
            abortSession,
            finalizeSession,
            getSessionStatus,
            listSessions,
            startSession,
            triggerStage,
        )

        _, client = _login()

        # 1. Start session
        result = startSession("hello-world-v1", client=client)
        session_id = result.get("sessionId") or result.get("id", "")
        assert session_id, f"No sessionId in response: {result}"

        try:
            # 2. Get session status
            status_result = getSessionStatus(session_id, client=client)
            assert "status" in status_result, f"No status in response: {status_result}"

            # 3. List sessions — verify our session appears
            sessions = listSessions(client=client).data
            session_ids = []
            for s in sessions:
                sid = s.get("sessionId") or s.get("id", "")
                session_ids.append(sid)
            assert session_id in session_ids, f"ndi_session {session_id} not in list: {session_ids}"

            # 4. Abort session (cleanup)
            try:
                abortSession(session_id, client=client)
            except Exception:
                # If session already finished, abort may 404
                pass

            # 5. triggerStage — just verify no crash
            try:
                triggerStage(session_id, "dummy-stage", client=client)
            except Exception:
                pass  # Expected: session may be gone

            # 6. finalizeSession — just verify no crash
            try:
                finalizeSession(session_id, client=client)
            except Exception:
                pass  # Expected: session may be gone

        except Exception:
            # Best-effort cleanup
            try:
                abortSession(session_id, client=client)
            except Exception:
                pass
            raise


# ===========================================================================
# TestZombie — Port of ZombieTest.m
# ===========================================================================


class TestZombie:
    """Port of ndi.unittest.cloud.compute.ZombieTest

    The zombie-test-v1 pipeline is designed to timeout after 2 minutes.
    This test starts it, monitors status, and waits for a final state.

    This is a long-running test (up to 10 minutes) so it's only run
    with live credentials and marked as slow.
    """

    def test_zombie_flow_mocked(self):
        """Zombie flow with mocked responses — verifies logic without waiting."""
        from ndi.cloud.api.compute import (
            getSessionStatus,
            startSession,
        )

        client = MagicMock()

        # Start returns session ID
        client.post.return_value = {"sessionId": "zombie-session-1"}
        result = startSession("zombie-test-v1", client=client)
        assert result["sessionId"] == "zombie-session-1"

        # Status returns RUNNING, then COMPLETED
        client.get.side_effect = [
            {
                "sessionId": "zombie-session-1",
                "status": "RUNNING",
                "currentStageId": "wait-and-die",
            },
            {
                "sessionId": "zombie-session-1",
                "status": "COMPLETED",
                "currentStageId": "wait-and-die",
            },
        ]

        status1 = getSessionStatus("zombie-session-1", client=client)
        assert status1["status"] == "RUNNING"

        status2 = getSessionStatus("zombie-session-1", client=client)
        assert status2["status"] == "COMPLETED"

    @requires_cloud
    @pytest.mark.slow
    def test_zombie_flow_live(self):
        """Port of ZombieTest.testZombieFlow — long-running pipeline test.

        Starts zombie-test-v1, polls status every 10 seconds, waits for
        ABORTED/FAILED/COMPLETED. Times out after 10 minutes.
        """
        from ndi.cloud.api.compute import (
            getSessionStatus,
            listSessions,
            startSession,
        )

        _, client = _login()

        # 1. Start pipeline
        result = startSession("zombie-test-v1", client=client)
        session_id = result.get("sessionId") or result.get("id", "")
        assert session_id, f"No sessionId in response: {result}"

        # 2. Initial wait
        time.sleep(10)

        # 3. Verify session in list
        sessions = listSessions(client=client).data
        session_ids = [s.get("sessionId") or s.get("id", "") for s in sessions]
        assert session_id in session_ids, f"ndi_session {session_id} not in list: {session_ids}"

        # 4. Polling loop — wait for final status
        max_iterations = 60  # 60 * 10s = 600s = 10 min
        final_status = None

        for _ in range(max_iterations):
            try:
                status_result = getSessionStatus(session_id, client=client)
                status = status_result.get("status", "UNKNOWN")

                if status in ("ABORTED", "FAILED", "COMPLETED"):
                    final_status = status
                    break
            except Exception:
                pass  # Retry on transient errors

            time.sleep(10)

        assert final_status is not None, (
            "Test timed out (10 min) before reaching a final status " "(ABORTED/FAILED/COMPLETED)"
        )
