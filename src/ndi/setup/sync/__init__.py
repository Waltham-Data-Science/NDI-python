"""Lab-specific synchronization rule setup.

Python equivalent of MATLAB's ``+ndi/+setup/+sync/``. Reads sync-rule
configuration JSON files from ``ndi_common/sync_rules/<lab_name>/`` and
installs the corresponding ``ndi.time.syncrule`` objects into a session's
syncgraph.

Each JSON file describes one sync rule with two top-level fields:

- ``syncrule_class`` -- full class name of the ``ndi.time.syncrule``
  subclass to instantiate (MATLAB dotted form, e.g.
  ``"ndi.time.syncrule.filematch"``).
- ``parameters`` -- an object passed directly to that class's constructor.

If no ``sync_rules/<lab_name>`` directory exists, the session is returned
unchanged; a lab is not required to define lab-specific rules.
"""

from __future__ import annotations

import json
from pathlib import Path

from ...time.syncrule import resolve_syncrule_class

__all__ = ["add_sync_rules", "syncrule_from_config_file"]


def _sync_rules_dir(lab_name: str) -> Path:
    """Return the vendored ``sync_rules/<lab_name>`` directory path."""
    import ndi.ndi_common

    return Path(ndi.ndi_common.__path__[0]) / "sync_rules" / lab_name


def syncrule_from_config_file(config_file_path: str | Path):
    """Construct an ``ndi.time.syncrule`` object from a JSON config file.

    Mirrors MATLAB ``ndi.setup.sync.syncRuleFromConfigFile``.

    Raises:
        FileNotFoundError: If ``config_file_path`` does not exist.
        ValueError: If the config is missing required fields or names a
            syncrule class that is not registered.
    """
    p = Path(config_file_path)
    if not p.is_file():
        raise FileNotFoundError(f"Sync rule configuration file not found: {p}")

    with open(p, encoding="utf-8") as f:
        cfg = json.load(f)

    if "syncrule_class" not in cfg or "parameters" not in cfg:
        raise ValueError(
            f"Sync rule configuration file ({p}) must contain both a "
            "'syncrule_class' field and a 'parameters' field."
        )

    rule_class = resolve_syncrule_class(cfg["syncrule_class"])
    return rule_class(parameters=cfg["parameters"])


def add_sync_rules(session, lab_name: str, force_update: bool = False):
    """Add lab-specific synchronization rules to a session's syncgraph.

    Reads every ``*.json`` file under ``ndi_common/sync_rules/<lab_name>/``
    and installs the corresponding syncrule via ``syncgraph_addrule``. Labs
    without a sync_rules directory are a no-op.

    Args:
        session: An ``ndi.session`` object.
        lab_name: Lab name whose sync rules should be installed.
        force_update: When true, existing rules with the same class and
            parameters are removed and re-added; when false (default),
            duplicate rules are skipped (as ``syncgraph_addrule`` already
            deduplicates).

    Returns:
        The session, mirroring MATLAB's ``S = ndi.setup.sync.addSyncRules(S, ...)``.
    """
    import_dir = _sync_rules_dir(lab_name)

    if not import_dir.is_dir():
        return session

    for config_path in sorted(import_dir.glob("*.json")):
        rule = syncrule_from_config_file(config_path)

        if force_update and hasattr(session, "syncgraph_rmrule"):
            try:
                session.syncgraph_rmrule(rule)
            except Exception:
                pass

        session.syncgraph_addrule(rule)

    return session
