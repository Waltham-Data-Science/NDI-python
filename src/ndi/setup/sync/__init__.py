"""ndi.setup.sync -- declarative lab-specific synchronization rules.

Python port of MATLAB's ``+ndi/+setup/+sync/`` package
(``addSyncRules.m``, ``syncRuleFromConfigFile.m``; NDI-matlab ``881919d39``).

Sync-rule definitions live in ``ndi_common/sync_rules/<labName>/*.json``, one
rule per file, and are the syncgraph counterpart to the DAQ-system JSONs in
``ndi_common/daq_systems/<labName>/``.  Each file has the shape::

    {
      "syncrule_class": "ndi.time.syncrule.filefind",
      "parameters": { ... }
    }

Usage::

    import ndi.setup.sync
    ndi.setup.sync.add_sync_rules(session, "vhlab")
"""

from .add_sync_rules import add_sync_rules, sync_rule_from_config_file

__all__ = ["add_sync_rules", "sync_rule_from_config_file"]
