"""
ndi.fun.data - Binary data grid and fit-curve utilities.

MATLAB equivalents: +ndi/+fun/+data/readngrid.m, writengrid.m, mat2ngrid.m,
                    evaluate_fitcurve.m, readImageStack.m
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

# Map type names to numpy dtypes
_TYPE_MAP: dict[str, np.dtype] = {
    "double": np.dtype("<f8"),
    "float64": np.dtype("<f8"),
    "single": np.dtype("<f4"),
    "float32": np.dtype("<f4"),
    "int8": np.dtype("<i1"),
    "int16": np.dtype("<i2"),
    "int32": np.dtype("<i4"),
    "int64": np.dtype("<i8"),
    "uint8": np.dtype("<u1"),
    "uint16": np.dtype("<u2"),
    "uint32": np.dtype("<u4"),
    "uint64": np.dtype("<u8"),
    "logical": np.dtype("bool"),
    "ubit1": np.dtype("bool"),
}


def readngrid(
    file_path: str | Path,
    data_size: Sequence[int],
    data_type: str = "double",
) -> np.ndarray:
    """Read n-dimensional binary matrix from file.

    MATLAB equivalent: ndi.fun.data.readngrid

    Args:
        file_path: Path to the binary file.
        data_size: Shape tuple, e.g. ``(100, 3)``.
        data_type: Element type name (``'double'``, ``'int16'``, etc.).

    Returns:
        numpy array with the given shape.

    Raises:
        ValueError: If data type is unknown or data count mismatches.
        FileNotFoundError: If file does not exist.
    """
    dtype = _TYPE_MAP.get(data_type)
    if dtype is None:
        raise ValueError(f"Unknown data type: '{data_type}'")

    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    expected = 1
    for d in data_size:
        expected *= d

    raw = np.fromfile(str(p), dtype=dtype)
    if raw.size != expected:
        raise ValueError(f"Data count mismatch: expected {expected}, got {raw.size}")
    return raw.reshape(data_size)


def writengrid(
    data: np.ndarray,
    file_path: str | Path,
    data_type: str = "double",
) -> None:
    """Write n-dimensional matrix to binary file in little-endian.

    MATLAB equivalent: ndi.fun.data.writengrid

    Args:
        data: numpy array to write.
        file_path: Output file path.
        data_type: Element type name.

    Raises:
        ValueError: If data type is unknown.
    """
    dtype = _TYPE_MAP.get(data_type)
    if dtype is None:
        raise ValueError(f"Unknown data type: '{data_type}'")
    arr = np.asarray(data, dtype=dtype)
    arr.tofile(str(file_path))


def mat2ngrid(
    data: np.ndarray,
    coordinates: list[np.ndarray] | None = None,
) -> dict[str, Any]:
    """Convert n-dimensional array to ngrid metadata structure.

    MATLAB equivalent: ndi.fun.data.mat2ngrid

    Args:
        data: The matrix data.
        coordinates: Optional list of coordinate vectors, one per dimension.

    Returns:
        Dict with ``data_size``, ``data_type``, ``data_dim``, ``coordinates``.
    """
    arr = np.asarray(data)

    # Reverse-map dtype to type name
    type_name = "double"
    for name, dt in _TYPE_MAP.items():
        if arr.dtype == dt:
            type_name = name
            break

    # Default coordinates: 0..N-1 per dimension
    if coordinates is None:
        coordinates = [np.arange(s, dtype="float64") for s in arr.shape]

    return {
        "data_size": arr.dtype.itemsize,
        "data_type": type_name,
        "data_dim": list(arr.shape),
        "coordinates": coordinates,
    }


def evaluate_fitcurve(
    fitcurve_doc: Any,
    *args: np.ndarray,
) -> np.ndarray:
    """Evaluate a fitted curve at given independent variable values.

    MATLAB equivalent: ndi.fun.data.evaluate_fitcurve

    Extracts the fit equation and parameters from a fitcurve document
    and evaluates the equation at the provided input values.

    Args:
        fitcurve_doc: A Document with ``fitcurve`` properties containing
            ``fit_equation``, ``fit_parameter_names``,
            ``fit_parameter_values``, and ``fit_variable_names``.
        *args: Arrays of independent variable values.

    Returns:
        Evaluated dependent variable values as a numpy array.

    Raises:
        ValueError: If the document has unsupported variable counts.
    """
    props = fitcurve_doc
    if hasattr(fitcurve_doc, "document_properties"):
        props = fitcurve_doc.document_properties

    fc = props.get("fitcurve", {}) if isinstance(props, dict) else {}

    equation = fc.get("fit_equation", "")
    param_names = fc.get("fit_parameter_names", [])
    param_values = fc.get("fit_parameter_values", [])
    var_names = fc.get("fit_variable_names", [])

    if not equation or not var_names:
        raise ValueError("fitcurve document missing equation or variable names")

    # Separate independent (all but last) and dependent (last) variables
    independent_names = var_names[:-1]
    var_names[-1]

    if len(independent_names) != len(args):
        raise ValueError(
            f"Expected {len(independent_names)} independent variable(s), " f"got {len(args)}"
        )

    # Build a safe local namespace for evaluation
    namespace: dict[str, Any] = {"np": np}
    # Standard math functions
    for fn in ("sin", "cos", "tan", "exp", "log", "log10", "sqrt", "abs", "pi", "inf", "nan"):
        namespace[fn] = getattr(np, fn, None) or getattr(np, fn, None)
    namespace["pi"] = np.pi
    namespace["inf"] = np.inf
    namespace["nan"] = np.nan
    namespace["power"] = np.power

    # Assign parameter values
    for name, val in zip(param_names, param_values):
        namespace[name] = float(val) if not isinstance(val, (list, np.ndarray)) else np.array(val)

    # Assign independent variable values
    for name, val in zip(independent_names, args):
        namespace[name] = np.asarray(val, dtype=float)

    # Evaluate the equation
    # The equation may use ^ for power (MATLAB style) - convert to **
    expr = equation.replace("^", "**")

    # Evaluate
    result = eval(expr, {"__builtins__": {}}, namespace)  # noqa: S307

    return np.asarray(result, dtype=float)


def read_image_stack(
    session: Any,
    doc: Any,
    fmt: str = "auto",
) -> tuple[np.ndarray, dict[str, Any]]:
    """Read an image stack or video from a database binary document.

    MATLAB equivalent: ndi.fun.data.readImageStack

    Args:
        session: The session or dataset object for database access.
        doc: Document or document ID specifying the binary file.
        fmt: Format string — ``'tif'``, ``'png'``, ``'mp4'``,
            ``'ngrid'`` (raw binary), or ``'auto'`` (detect from
            file header, falling back to ngrid).

    Returns:
        Tuple ``(image_data, info)`` where *image_data* is a numpy
        array (H x W or H x W x C) for images, and *info* is metadata.

    Raises:
        ImportError: If PIL/Pillow is not installed (for image formats).
        ValueError: If the format is not recognized or data cannot be read.
    """
    image_formats = {"tif", "tiff", "png", "jpg", "jpeg", "bmp", "gif"}
    video_formats = {"mp4", "avi", "mov", "mkv", "wmv"}

    fmt_lower = fmt.lower()

    # Get binary file data from the database
    binary_data: bytes | Path | None = None
    if hasattr(session, "database_openbinarydoc"):
        fobj = session.database_openbinarydoc(doc, "imageStack")
        try:
            if hasattr(fobj, "read"):
                binary_data = fobj.read()
            elif hasattr(fobj, "fullpathfilename"):
                binary_data = Path(fobj.fullpathfilename)
        finally:
            if hasattr(fobj, "close"):
                fobj.close()

    if binary_data is None:
        raise ValueError("Could not read binary data from document")

    # --- Auto-detect format from file header ---
    if fmt_lower == "auto":
        raw = binary_data if isinstance(binary_data, (bytes, bytearray)) else None
        if raw is None and isinstance(binary_data, Path):
            with open(binary_data, "rb") as f:
                raw = f.read(8)

        if raw is not None:
            if raw[:4] == b"\x89PNG":
                fmt_lower = "png"
            elif raw[:2] in (b"II", b"MM"):
                fmt_lower = "tif"
            elif raw[:3] == b"\xff\xd8\xff":
                fmt_lower = "jpg"
            elif raw[:4] == b"GIF8":
                fmt_lower = "gif"
            elif raw[:2] == b"BM":
                fmt_lower = "bmp"
            else:
                fmt_lower = "ngrid"
        else:
            fmt_lower = "ngrid"

    # --- Image formats (PIL-readable) ---
    if fmt_lower in image_formats:
        try:
            from PIL import Image
        except ImportError as exc:
            raise ImportError(
                "Pillow is required for read_image_stack. " "Install it with: pip install Pillow"
            ) from exc

        import io

        if isinstance(binary_data, (bytes, bytearray)):
            img = Image.open(io.BytesIO(binary_data))
        elif isinstance(binary_data, Path):
            img = Image.open(str(binary_data))
        else:
            raise ValueError("Could not read image data from document")

        frames = []
        try:
            while True:
                frames.append(np.array(img))
                img.seek(img.tell() + 1)
        except EOFError:
            pass

        if len(frames) == 1:
            stack = frames[0]
        else:
            stack = np.stack(frames, axis=-1)

        info: dict[str, Any] = {
            "format": fmt_lower,
            "size": img.size,
            "mode": img.mode,
            "num_frames": len(frames),
        }
        return stack, info

    # --- Raw binary (ngrid) format ---
    if fmt_lower == "ngrid":
        # Get data_type and dimension_size from document properties
        props = doc.document_properties if hasattr(doc, "document_properties") else {}
        is_params = props.get("imageStack_parameters", {})
        data_type = is_params.get("data_type", "uint8")
        dim_size = is_params.get("dimension_size", [])

        np_dtype = _TYPE_MAP.get(data_type, np.dtype("<u1"))

        if isinstance(binary_data, (bytes, bytearray)):
            raw_arr = np.frombuffer(binary_data, dtype=np_dtype)
        elif isinstance(binary_data, Path):
            raw_arr = np.fromfile(str(binary_data), dtype=np_dtype)
        else:
            raise ValueError("Could not read ngrid data from document")

        if len(dim_size) >= 2:
            expected = int(dim_size[0]) * int(dim_size[1])
            if raw_arr.size >= expected:
                stack = raw_arr[:expected].reshape(int(dim_size[1]), int(dim_size[0]))
            else:
                stack = raw_arr
        else:
            stack = raw_arr

        info = {
            "format": "ngrid",
            "data_type": data_type,
            "dimension_size": list(dim_size),
        }
        return stack, info

    # --- Video formats ---
    if fmt_lower in video_formats:
        try:
            import cv2
        except ImportError as exc:
            raise ImportError(
                "OpenCV is required for video reading. "
                "Install it with: pip install opencv-python"
            ) from exc

        import tempfile

        if isinstance(binary_data, Path):
            video_path = str(binary_data)
        elif isinstance(binary_data, (bytes, bytearray)):
            tmp = tempfile.NamedTemporaryFile(
                suffix=f".{fmt_lower}",
                delete=False,
            )
            tmp.write(binary_data)
            tmp.close()
            video_path = tmp.name
        else:
            raise ValueError("Could not read video data from document")

        cap = cv2.VideoCapture(video_path)
        frames = []
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)
        cap.release()

        info = {
            "format": fmt_lower,
            "num_frames": len(frames),
            "fps": cap.get(cv2.CAP_PROP_FPS) if frames else 0,
        }

        stack = np.stack(frames, axis=0) if frames else np.array([])
        return stack, info

    raise ValueError(f"Format '{fmt}' is not a recognized image or video format.")
