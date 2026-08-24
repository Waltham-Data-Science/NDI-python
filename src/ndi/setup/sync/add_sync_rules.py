"""Install a lab's pre-configured synchronization rules into a session.

MATLAB equivalents:

* ``src/ndi/+ndi/+setup/+sync/addSyncRules.m``
* ``src/ndi/+ndi/+setup/+sync/syncRuleFromConfigFile.m``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...time.syncrule_base import ndi_time_syncrule, syncrule_class_from_name


def _sync_rules_dir(lab_name: str) -> Path:
    """Return ``ndi_common/sync_rules/<lab_name>`` (may not exist)."""
    import ndi.ndi_common

    return Path(ndi.ndi_common.__path__[0]) / "sync_rules" / str(lab_name)


def sync_rule_from_config_file(config_file_path: str | Path) -> ndi_time_syncrule:
    """Construct an ``ndi.time.syncrule`` from a JSON config file.

    The JSON file must contain both:

    ``syncrule_class``
        Full class name of the sync-rule class to instantiate, in either the
        MATLAB dotted form (``"ndi.time.syncrule.filefind"``) or the Python
        underscore form.
    ``parameters``
        A mapping of parameters passed straight to that class's constructor.

    Parameters
    ----------
    config_file_path : str or pathlib.Path
        Path to an existing JSON configuration file.

    Returns
    -------
    ndi.time.syncrule_base.ndi_time_syncrule
        The constructed sync rule.

    Raises
    ------
    FileNotFoundError
        If the config file does not exist.
    ValueError
        If the config is missing ``syncrule_class`` or ``parameters``, or names
        a sync-rule class that does not exist.

    Notes
    -----
    MATLAB raises ``NDI:Setup:InvalidSyncRuleConfig`` for a malformed config;
    the Python port raises :class:`ValueError` naming the same two fields.
    """
    path = Path(config_file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Sync rule configuration file not found: {path}")

    with open(path, encoding="utf-8") as f:
        config: Any = json.load(f)

    if not isinstance(config, dict) or "syncrule_class" not in config or "parameters" not in config:
        raise ValueError(
            f"Sync rule configuration file ({path}) must contain both a "
            "'syncrule_class' field and a 'parameters' field."
        )

    rule_class = syncrule_class_from_name(config["syncrule_class"])
    return rule_class(parameters=config["parameters"])


def add_sync_rules(session, lab_name: str):
    """Add the sync rules pre-configured for ``lab_name`` to ``session``.

    Rule definitions are read from ``ndi_common/sync_rules/<lab_name>/*.json``.
    If that folder does not exist the session is returned unchanged -- a lab is
    not required to define any lab-specific rules.  Rules already present in the
    syncgraph are not added again (``ndi.time.syncgraph.add_rule`` dedupes on
    parameters, matching MATLAB ``ndi.time.syncrule/eq``).

    Parameters
    ----------
    session : ndi.session.session_base.ndi_session
        The session whose syncgraph should receive the rules.
    lab_name : str
        Name of the lab, e.g. ``"vhlab"``.

    Returns
    -------
    ndi.session.session_base.ndi_session
        The same session, for chaining (mirrors MATLAB's value semantics).
    """
    import_dir = _sync_rules_dir(lab_name)

    if not import_dir.is_dir():
        return session  # no lab-specific sync rules are defined for this lab

    for config_file in sorted(import_dir.glob("*.json")):
        rule = sync_rule_from_config_file(config_file)
        session.syncgraph_addrule(rule)

    return session
