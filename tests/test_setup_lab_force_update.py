"""``ndi.setup.lab`` leaves an installed DAQ system alone, or replaces it.

MATLAB counterpart: ``+ndi/+setup/lab.m`` and ``+ndi/+setup/rayolab.m``,
which gained a ``'forceUpdate'`` name-value argument, and
``+ndi/+setup/+daq/addDaqSystems.m``, which is where the behaviour lives::

    device = S.daqsystem_load('name', deviceNames{i});
    if force && ~isempty(device)
        S.daqsystem_rm(device);
        device = [];
    end
    if isempty(device)
        ... add it ...
    end

Two things follow from that, and Python did neither. Setting a lab up twice
built a second copy of every DAQ system, because nothing asked whether one
was already there; and there was no way to reinstall a DAQ system whose
definition had changed, because ``force_update`` reached only
``add_sync_rules``. The first is the one that bites without being noticed:
nothing errors, the session simply ends up with duplicates.
"""

from __future__ import annotations

import pytest


class _Doc:
    def __init__(self, doc_type, props):
        self.doc_type = doc_type
        self.props = props
        self.id = f"{doc_type}:{props.get('base.name', '')}:{id(self)}"

    def set_dependency_value(self, *args, **kwargs):
        return self

    def add_dependency_value_n(self, *args, **kwargs):
        return self


class _DaqSystem:
    """Just enough of an ndi.daq.system to be found and removed."""

    def __init__(self, name):
        self.name = name


class _Session:
    """Records what was installed, and reports it back to the next call.

    ``daqsystem_load`` matching on name is what lets the second ``lab()``
    call see the first one's work -- the real session searches the database
    for daqsystem documents, this keeps the list directly.
    """

    def __init__(self, installed=()):
        self.docs: list[_Doc] = []
        self.sync_rules: list = []
        self.installed = [_DaqSystem(name) for name in installed]
        self.removed: list[str] = []

    def newdocument(self, doc_type, **kwargs):
        return _Doc(doc_type, kwargs)

    def database_add(self, doc):
        self.docs.append(doc)
        if doc.doc_type == "daq/daqsystem":
            self.installed.append(_DaqSystem(doc.props["base.name"]))

    def syncgraph_addrule(self, rule):
        self.sync_rules.append(rule)

    def daqsystem_load(self, name=None, **kwargs):
        found = [daq for daq in self.installed if daq.name == name]
        if not found:
            return None
        return found[0] if len(found) == 1 else found

    def daqsystem_rm(self, dev):
        self.removed.append(dev.name)
        self.installed = [daq for daq in self.installed if daq.name != dev.name]


LAB = "rayolab"


def _system_names(session: _Session) -> list[str]:
    return sorted(d.props["base.name"] for d in session.docs if d.doc_type == "daq/daqsystem")


@pytest.fixture
def lab_fn():
    from ndi.setup.lab import lab

    return lab


class TestASecondSetupIsANoOp:
    def test_installing_twice_does_not_duplicate(self, lab_fn):
        session = _Session()
        lab_fn(session, LAB)
        after_first = _system_names(session)
        assert after_first, "the fixture lab must define at least one DAQ system"

        lab_fn(session, LAB)
        assert _system_names(session) == after_first

    def test_nothing_is_removed_without_force(self, lab_fn):
        session = _Session()
        lab_fn(session, LAB)
        lab_fn(session, LAB)
        assert session.removed == []


class TestForceUpdateReinstalls:
    def test_the_existing_system_is_removed_first(self, lab_fn):
        session = _Session()
        lab_fn(session, LAB)
        installed = _system_names(session)

        lab_fn(session, LAB, force_update=True)

        assert sorted(set(session.removed)) == installed

    def test_and_re_created_from_the_current_definition(self, lab_fn):
        session = _Session()
        lab_fn(session, LAB)
        first_pass = _system_names(session)

        lab_fn(session, LAB, force_update=True)

        # One entry per install, so each name appears twice: removed and
        # written again, rather than skipped.
        assert _system_names(session) == sorted(first_pass + first_pass)


class TestRayolabPassesItThrough:
    """The wrapper is where MATLAB threads the option, so check it does."""

    def test_force_update_reaches_lab(self):
        from ndi.setup.rayolab import rayolab

        session = _Session()
        rayolab(session)
        installed = _system_names(session)

        rayolab(session, force_update=True)

        assert sorted(set(session.removed)) == installed

    def test_the_default_still_skips(self):
        from ndi.setup.rayolab import rayolab

        session = _Session()
        rayolab(session)
        rayolab(session)
        assert session.removed == []
