"""
ndi.validators.mustBeClassnameOfType

MATLAB equivalent: +ndi/+validators/mustBeClassnameOfType.m

Validates that a class name string refers to a class that is a subclass
of a required type.
"""

from __future__ import annotations

import importlib


def mustBeClassnameOfType(classname: str, requiredType: type) -> None:
    """Validate that *classname* resolves to a subclass of *requiredType*.

    MATLAB equivalent:
    ``ndi.validators.mustBeClassnameOfType(classname, requiredType)``

    *classname* is a fully-qualified Python class name
    (e.g. ``"ndi.session.DirSession"``).  The function dynamically imports
    the module, looks up the class, and checks ``issubclass``.

    Parameters
    ----------
    classname : str
        Fully-qualified class name (``"package.module.ClassName"``).
    requiredType : type
        The base class that *classname* must inherit from.

    Raises
    ------
    TypeError
        If *classname* is not a string.
    ValueError
        If the class cannot be found or does not inherit from
        *requiredType*.
    """
    if not isinstance(classname, str):
        raise TypeError("classname must be a string.")

    parts = classname.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Class {classname!r} is not a fully-qualified name.")

    module_path, class_attr = parts
    try:
        mod = importlib.import_module(module_path)
    except ModuleNotFoundError:
        raise ValueError(f"Module {module_path!r} does not exist.") from None

    cls = getattr(mod, class_attr, None)
    if cls is None or not isinstance(cls, type):
        raise ValueError(f"Class {classname!r} does not exist.")

    if not issubclass(cls, requiredType):
        raise ValueError(
            f"Class {classname!r} must be a subclass of "
            f"{requiredType.__name__!r}."
        )
