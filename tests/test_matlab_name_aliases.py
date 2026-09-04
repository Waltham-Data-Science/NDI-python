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
from ndi.file.type.mfdaq_epoch_channel import ndi_file_type_mfdaq__epoch__channel
from ndi.gui.cloud_colors import CloudColors
from ndi.gui.component.abstract.ProgressMonitor import (
    ndi_gui_component_abstract_ProgressMonitor,
)
from ndi.gui.component.CommandWindowProgressMonitor import (
    ndi_gui_component_CommandWindowProgressMonitor,
)
from ndi.gui.component.internal.AsynchProgressTracker import (
    ndi_gui_component_internal_AsynchProgressTracker,
)
from ndi.gui.component.internal.ProgressTracker import (
    ndi_gui_component_internal_ProgressTracker,
)
from ndi.gui.component.NDIProgressBar import ndi_gui_component_NDIProgressBar
from ndi.gui.component.ProgressBarWindow import ndi_gui_component_ProgressBarWindow
from ndi.gui.data import ndi_gui_Data
from ndi.gui.docViewer import ndi_gui_docViewer
from ndi.gui.icon import ndi_gui_Icon
from ndi.gui.lab import ndi_gui_Lab
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
COVERED = [
    ndi_session,
    ndi_session_dir,
    _DatasetBase,
    ndi_file_type_mfdaq__epoch__channel,
    ndi_gui_component_abstract_ProgressMonitor,
    ndi_gui_component_CommandWindowProgressMonitor,
    ndi_gui_component_NDIProgressBar,
    ndi_gui_component_ProgressBarWindow,
    ndi_gui_component_internal_ProgressTracker,
    ndi_gui_component_internal_AsynchProgressTracker,
    ndi_gui_Data,
    ndi_gui_docViewer,
    ndi_gui_Icon,
    ndi_gui_Lab,
]

#: A camelCase method that is overridden, and the base it overrides. An alias
#: placed only on the base would bind the BASE implementation while the
#: camelCase name binds the override -- two names for "the same method" that
#: quietly do different things, and nothing would raise.
OVERRIDDEN = [
    (
        ndi_gui_component_NDIProgressBar,
        ndi_gui_component_abstract_ProgressMonitor,
        "updateProgressDisplay",
        "update_progress_display",
    ),
    (
        ndi_gui_component_NDIProgressBar,
        ndi_gui_component_abstract_ProgressMonitor,
        "updateMessage",
        "update_message",
    ),
    (
        ndi_gui_component_CommandWindowProgressMonitor,
        ndi_gui_component_abstract_ProgressMonitor,
        "updateProgressDisplay",
        "update_progress_display",
    ),
    (
        ndi_gui_component_CommandWindowProgressMonitor,
        ndi_gui_component_abstract_ProgressMonitor,
        "updateMessage",
        "update_message",
    ),
    (
        ndi_gui_component_internal_AsynchProgressTracker,
        ndi_gui_component_internal_ProgressTracker,
        "updateProgress",
        "update_progress",
    ),
]


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
    def test_the_convention_is_documented_where_a_reader_would_look(self, cls):
        """Someone reading the code should learn why there are two names,
        not have to infer it from the aliases.

        The class docstring or its module's will do. The three core classes
        carry it themselves; the GUI modules carry it once at module level
        rather than repeating the same paragraph on every small class in the
        file.
        """
        import sys

        module_doc = getattr(sys.modules.get(cls.__module__), "__doc__", "") or ""
        assert "CROSS-LANGUAGE NAMING" in (cls.__doc__ or "") + module_doc


class TestOverridesSurviveTheirAlias:
    """The trap this convention can fall into, and does not.

    An alias on an abstract base binds the BASE implementation. A subclass
    that overrides the camelCase method would then have two names that
    disagree -- and neither raises, so nothing would notice.
    """

    @pytest.mark.parametrize(
        "cls,base,camel,snake", OVERRIDDEN, ids=[f"{c.__name__}.{s}" for c, _, _, s in OVERRIDDEN]
    )
    def test_the_alias_binds_the_subclass_implementation(self, cls, base, camel, snake):
        own = inspect.getattr_static(cls, camel)
        assert inspect.getattr_static(cls, snake) is own
        assert inspect.getattr_static(cls, snake) is not inspect.getattr_static(base, snake)

    def test_a_base_only_alias_really_would_be_wrong(self):
        """Proof the case above is worth testing: with the alias only on the
        base, the two names return different things."""

        class Base:
            def updateMessage(self):  # noqa: N802
                return "base"

            update_message = updateMessage

        class Child(Base):
            def updateMessage(self):  # noqa: N802
                return "child"

        child = Child()
        assert child.updateMessage() == "child"
        assert child.update_message() == "base"


class TestCloudColorsIsExemptForAReason:
    """CloudColors is deliberately NOT in COVERED.

    Its camelCase names are @property accessors over a NamedTuple's
    snake_case fields, so both spellings already resolve -- they are simply
    not the same OBJECT, which is all the guard can see. Adding an alias
    would be a third name for the same value.
    """

    @pytest.mark.parametrize(
        "camel,snake",
        [
            ("darkBlue", "dark_blue"),
            ("lightBlue", "light_blue"),
            ("offWhite", "off_white"),
            ("okGreen", "ok_green"),
            ("warnAmber", "warn_amber"),
            ("neutralGrey", "neutral_grey"),
        ],
    )
    def test_both_spellings_resolve_to_the_same_value(self, camel, snake):
        colors = CloudColors()
        assert getattr(colors, camel) == getattr(colors, snake)

    def test_the_camelcase_name_is_a_property_not_a_stored_field(self):
        assert isinstance(inspect.getattr_static(CloudColors, "darkBlue"), property)


if __name__ == "__main__":
    pytest.main([__file__])
