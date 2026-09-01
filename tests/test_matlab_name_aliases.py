"""Every MATLAB-named method on the core classes answers to both spellings.

MATLAB counterparts: ndi.session, ndi.session.dir, ndi.dataset

Methods that mirror MATLAB keep MATLAB's exact name and also carry a
snake_case alias bound to the same function. The failure this prevents is an
AttributeError in whichever direction the caller came from:

    s.isIngested()              a MATLAB script, ported
    s.is_ingested_in_dataset()  idiomatic Python

Before this, the first failed (Python had renamed it ``is_fully_ingested``)
and the second failed too (Python had kept only ``isIngestedInDataset``) --
so neither audience could rely on a spelling.

The last test is the one that matters over time: it FAILS when a new
camelCase method is added to these classes without an alias, so the
convention cannot quietly erode the way it did before.
"""

from __future__ import annotations

import inspect
import re

import pytest

from ndi.dataset import _DatasetBase
from ndi.session.dir import ndi_session_dir
from ndi.session.session_base import ndi_session

#: (class, MATLAB name, snake_case name) for every aliased method.
ALIASES = [
    (ndi_session, "is_fully_ingested", "isIngested"),
    (ndi_session, "isIngestedInDataset", "is_ingested_in_dataset"),
    (ndi_session_dir, "setObjectTypeMarker", "set_object_type_marker"),
    (ndi_session_dir, "updateObjectTypeMarker", "update_object_type_marker"),
    (ndi_session_dir, "deleteSessionDataStructures", "delete_session_data_structures"),
    (_DatasetBase, "deleteIngestedSession", "delete_ingested_session"),
    (_DatasetBase, "repairDatasetSessionInfo", "repair_dataset_session_info"),
    (_DatasetBase, "addSessionInfoToDataset", "add_session_info_to_dataset"),
    (_DatasetBase, "removeSessionInfoFromDataset", "remove_session_info_from_dataset"),
]

#: The classes the convention covers.
COVERED = [ndi_session, ndi_session_dir, _DatasetBase]


def _snake(name: str) -> str:
    """camelCase -> snake_case, mechanically."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _snake_names_for(cls, member) -> list[str]:
    """Every snake_case attribute on CLS bound to the same object as MEMBER.

    The rule is "reachable under SOME snake_case name", not "reachable under
    the mechanical transform of this one". ``isIngested`` transforms to
    ``is_ingested``, but the Python method it aliases is
    ``is_fully_ingested`` -- and inventing a third spelling to satisfy a
    string rule would be worse than the problem.
    """
    target = inspect.getattr_static(cls, member) if isinstance(member, str) else member
    found = []
    for klass in cls.__mro__:
        for name, value in vars(klass).items():
            if name.startswith("_") or re.search(r"[a-z][A-Z]", name):
                continue
            if value is target:
                found.append(name)
    return found


class TestBothSpellingsExist:
    @pytest.mark.parametrize("cls,a,b", ALIASES, ids=[f"{a}" for _, a, b in ALIASES])
    def test_both_names_resolve(self, cls, a, b):
        assert hasattr(cls, a)
        assert hasattr(cls, b)

    @pytest.mark.parametrize("cls,a,b", ALIASES, ids=[f"{a}" for _, a, b in ALIASES])
    def test_they_are_the_same_function(self, cls, a, b):
        """An alias, not a copy -- so a fix to one is a fix to both, and
        patching one in a test patches the other."""
        assert getattr(cls, a) is getattr(cls, b)

    @pytest.mark.parametrize("cls,a,b", ALIASES, ids=[f"{a}" for _, a, b in ALIASES])
    def test_the_alias_keeps_its_staticmethod_or_instance_nature(self, cls, a, b):
        """Three of these are @staticmethod. A class-level alias must not
        turn one into an unbound function that silently swallows an argument
        as `self`."""
        original = inspect.getattr_static(cls, a)
        alias = inspect.getattr_static(cls, b)
        assert type(original) is type(alias)


class TestTheTwoDirectionsThatUsedToFail:
    def test_a_ported_matlab_script_can_call_isIngested(self):
        """MATLAB's name for what Python calls is_fully_ingested."""
        assert ndi_session.isIngested is ndi_session.is_fully_ingested

    def test_python_code_can_call_is_ingested_in_dataset(self):
        assert ndi_session.is_ingested_in_dataset is ndi_session.isIngestedInDataset


class TestTheConventionCannotErode:
    def test_every_camelcase_method_has_a_snake_case_alias(self):
        """The regression guard. A new MATLAB-named method added to these
        classes without an alias fails here, which is how the convention
        stays true rather than drifting again."""
        missing = []
        for cls in COVERED:
            for name, member in vars(cls).items():
                if name.startswith("_") or not re.search(r"[a-z][A-Z]", name):
                    continue
                if not callable(member) and not isinstance(
                    member, (staticmethod, classmethod, property)
                ):
                    continue
                if not _snake_names_for(cls, member):
                    missing.append(f"{cls.__name__}.{name} (expected e.g. {_snake(name)})")
        assert not missing, "camelCase methods with no snake_case alias: " + ", ".join(missing)

    def test_the_guard_would_actually_catch_one(self):
        """A guard that cannot fail is worse than none, so this proves the
        rule above rejects an un-aliased camelCase method."""

        class Drifted:
            def someNewThing(self):  # noqa: N802
                return 1

        offenders = [
            name
            for name, member in vars(Drifted).items()
            if not name.startswith("_")
            and re.search(r"[a-z][A-Z]", name)
            and not _snake_names_for(Drifted, member)
        ]
        assert offenders == ["someNewThing"]

    def test_an_alias_under_a_differently_worded_name_satisfies_the_guard(self):
        """isIngested is reachable as is_fully_ingested, not is_ingested --
        the guard must accept that rather than demanding a third spelling."""
        assert _snake_names_for(ndi_session, "isIngested") == ["is_fully_ingested"]


class TestTheClassNoteExists:
    @pytest.mark.parametrize("cls", COVERED, ids=lambda c: c.__name__)
    def test_the_convention_is_documented_on_the_class(self, cls):
        """Someone reading the class should learn why there are two names,
        not have to infer it from the aliases."""
        assert "CROSS-LANGUAGE NAMING" in (cls.__doc__ or "")


if __name__ == "__main__":
    pytest.main([__file__])
