"""daqsystem_load name searches, against MATLAB's ndi.session/daqsystem_load.

MATLAB counterpart: ``src/ndi/+ndi/session.m`` (``daqsystem_load``,
``isMatchAllRegexp``; tests: ``tests/+ndi/+unittest/+session/TestDaqsystemLoadName.m``)

A ``name`` that matches every name (``'(.*)'``, ``'.*'``) is dropped from the
database search -- a regexp search is slow on large databases and cannot
narrow the result -- so it must return the same DAQ systems as no name at
all, while a specific name still filters.

Building the session also exercises ``daqsystem_add``, which called
``dev.setsession`` -- a method the Python DAQ system does not have (it is
``set_session``) -- so adding any DAQ system raised AttributeError.
"""

from __future__ import annotations

import pytest

from ndi.session.session_base import ndi_session


class TestIsMatchAllRegexp:
    @pytest.mark.parametrize("value", ["(.*)", ".*", "^(.*)$", "^.*", ".*$"])
    def test_match_all(self, value):
        assert ndi_session.isMatchAllRegexp(value) is True

    @pytest.mark.parametrize("value", ["intan1", "(.+)", "a.*", "", 5, None, ["(.*)"]])
    def test_not_match_all(self, value):
        assert ndi_session.isMatchAllRegexp(value) is False


@pytest.fixture
def session(tmp_path):
    from ndi.daq.reader.mfdaq import ndi_daq_reader_mfdaq_intan
    from ndi.daq.system_mfdaq import ndi_daq_system_mfdaq
    from ndi.file.navigator import ndi_file_navigator
    from ndi.session import ndi_session_dir

    (tmp_path / "rec1.rhd").write_text("x")
    s = ndi_session_dir("exp1", str(tmp_path))
    for name in ("intan1", "intan2"):
        nav = ndi_file_navigator(s, ["#.rhd"])
        s.daqsystem_add(ndi_daq_system_mfdaq(name, nav, ndi_daq_reader_mfdaq_intan()))
    return s


def _ids(daqs):
    if daqs is None:
        return []
    daqs = daqs if isinstance(daqs, list) else [daqs]
    return sorted(d.id for d in daqs)


class TestDaqsystemLoadName:
    def test_match_all_name_equals_no_name(self, session):
        everything = session.daqsystem_load()
        assert len(_ids(everything)) == 2
        assert _ids(session.daqsystem_load(name="(.*)")) == _ids(everything)
        assert _ids(session.daqsystem_load(name=".*")) == _ids(everything)

    def test_a_specific_name_still_filters(self, session):
        d = session.daqsystem_load(name="intan1")
        assert d.name == "intan1"
        assert session.daqsystem_load(name="no_such_daqsystem") is None

    def test_a_match_all_name_sends_no_regexp(self, session, monkeypatch):
        seen = []
        real = session.database_search
        monkeypatch.setattr(
            session, "database_search", lambda q: seen.append(q.to_search_structure()) or real(q)
        )
        session.daqsystem_load(name="(.*)")
        assert "regexp" not in repr(seen[0])


class TestExactNameCallers:
    """``name`` is a regex, so callers that mean one system anchor it.

    ``daqsystem_rm`` on 'intan1' must not also delete 'intan1_nidq'
    (vhlab: 'vhneuropixelsGLX' and 'vhneuropixelsGLX_nidq').
    """

    @pytest.fixture
    def prefixed(self, session, tmp_path):
        from ndi.daq.reader.mfdaq import ndi_daq_reader_mfdaq_intan
        from ndi.daq.system_mfdaq import ndi_daq_system_mfdaq
        from ndi.file.navigator import ndi_file_navigator

        nav = ndi_file_navigator(session, ["#.rhd"])
        session.daqsystem_add(
            ndi_daq_system_mfdaq("intan1_nidq", nav, ndi_daq_reader_mfdaq_intan())
        )
        return session

    def test_exact_name_regexp(self):
        assert ndi_session._exact_name_regexp("intan1") == "^intan1$"

    def test_a_bare_name_is_still_a_regexp(self, prefixed):
        assert len(prefixed.daqsystem_load(name="intan1")) == 2

    def test_rm_removes_only_the_named_system(self, prefixed):
        d = prefixed.daqsystem_load(name=ndi_session._exact_name_regexp("intan1"))
        assert d.name == "intan1"
        prefixed.daqsystem_rm(d)
        names = sorted(x.name for x in _as_list(prefixed.daqsystem_load()))
        assert names == ["intan1_nidq", "intan2"]


def _as_list(d):
    if d is None:
        return []
    return d if isinstance(d, list) else [d]
