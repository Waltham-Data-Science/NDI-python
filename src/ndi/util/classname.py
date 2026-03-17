"""
ndi.util.classname - Convert between Python and MATLAB class names.

The NDI naming convention maps mechanically between the two languages:

* MATLAB uses dots as package separators: ``ndi.session.dir``
* Python uses single underscores:        ``ndi_session_dir``
* A literal underscore in MATLAB (``ndi.calc.tuning_fit``) becomes a
  double underscore in Python (``ndi_calc_tuning__fit``).

The two helper functions in this module perform the conversion in each
direction so that class names stored in documents or artifacts are
always in the canonical MATLAB form and can be read by either language.
"""

from __future__ import annotations


def ndi_matlab_classname(obj_or_name: object | str) -> str:
    """Return the MATLAB-style dotted class name.

    Parameters
    ----------
    obj_or_name
        Either a Python object whose ``type().__name__`` will be used,
        or a string that is already a Python-style underscore name
        (e.g. ``"ndi_session_dir"``).  If the string is already in
        MATLAB dot-notation it is returned unchanged.

    Returns
    -------
    str
        MATLAB class name, e.g. ``"ndi.session.dir"``.

    Examples
    --------
    >>> ndi_matlab_classname("ndi_session_dir")
    'ndi.session.dir'
    >>> ndi_matlab_classname("ndi_calc_tuning__fit")
    'ndi.calc.tuning_fit'
    >>> ndi_matlab_classname("ndi.session.dir")
    'ndi.session.dir'
    """
    name = obj_or_name if isinstance(obj_or_name, str) else type(obj_or_name).__name__
    if "." in name:
        return name  # already MATLAB-style
    # "__" → literal underscore, then "_" → dot
    return name.replace("__", "\x00").replace("_", ".").replace("\x00", "_")


def ndi_python_classname(name: str) -> str:
    """Return the Python-style underscore class name.

    Parameters
    ----------
    name
        A MATLAB-style dotted name (e.g. ``"ndi.session.dir"``).
        If the string is already in Python underscore notation it is
        returned unchanged.

    Returns
    -------
    str
        Python class name, e.g. ``"ndi_session_dir"``.

    Examples
    --------
    >>> ndi_python_classname("ndi.session.dir")
    'ndi_session_dir'
    >>> ndi_python_classname("ndi.calc.tuning_fit")
    'ndi_calc_tuning__fit'
    >>> ndi_python_classname("ndi_session_dir")
    'ndi_session_dir'
    """
    if "." not in name:
        return name  # already Python-style
    # literal "_" → "__", then "." → "_"
    return name.replace("_", "__").replace(".", "_")
