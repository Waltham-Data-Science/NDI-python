"""ndi.update.check_on_startup - a quiet, at-most-daily update check.

MATLAB counterpart: ``src/ndi/+ndi/+update/checkOnStartup.m``
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from pydantic import validate_call

__all__ = ["checkOnStartup", "LAST_CHECK_PREFERENCE"]

#: Kept apart from NDI-matlab's Update.MATLAB.LastCheckTime: both languages
#: share NDI_Preferences.json, and one checking must not hold the other's
#: check off for a day, since they check different repositories.
LAST_CHECK_PREFERENCE = "Update.Python.LastCheckTime"

_FORMAT = "%Y-%m-%dT%H:%M:%S"


@validate_call
def checkOnStartup() -> str:
    """Check for an NDI-python update, at most once per interval.

    MATLAB::

        ndi.update.checkOnStartup()

    If the preference ``Update.CheckOnStartup`` is true and at least
    ``Update.CheckIntervalDays`` days have passed since the last check
    (``Update.Python.LastCheckTime``), runs :func:`ndi.update.check` quietly
    and prints one line if an update is available. It never raises: a failed
    check (for example, no network) is ignored until the next interval.

    Skipped when the environment variable ``CI`` is set, so automated test
    runs are not slowed down.

    To turn the check off::

        ndi.preferences.set("Update.CheckOnStartup", False)

    Returns:
        The line printed, or ``""``.

    Python-specific Notes:
        NDI-python has no ``ndi_Init``; the navigator calls this when it
        opens. Importing ``ndi`` never does, so a library import never goes
        to the network. MATLAB returns nothing; the line is returned so a
        caller (or a test) can see what was said.
    """
    try:
        from .. import preferences
        from .check import check

        if os.environ.get("CI") or not preferences.get("Update.CheckOnStartup"):
            return ""

        now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
        last_text = str(preferences.get(LAST_CHECK_PREFERENCE) or "")
        interval = float(preferences.get("Update.CheckIntervalDays"))
        if last_text:
            try:
                if now - datetime.strptime(last_text, _FORMAT) < timedelta(days=interval):
                    return ""
            except ValueError:
                pass  # an unreadable time: check now and overwrite it
        # Record the attempt first, so a failing check is not retried at
        # every start.
        preferences.set(LAST_CHECK_PREFERENCE, now.strftime(_FORMAT))

        result = check(Verbose=False, Timeout=5)
        if not result["UpdateAvailable"]:
            return ""
        first = result["Message"].splitlines()[0]
        if result["CanInstall"]:
            line = f"{first} Run ndi.update.install() (or `ndi update`) to update."
        else:
            line = first
        print(line)
        return line
    except Exception:  # noqa: BLE001 - never let an update check break startup
        return ""
