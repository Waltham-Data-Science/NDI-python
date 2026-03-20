"""Shared helpers for ingestion-based symmetry makeArtifacts tests.

Provides functions to locate example data files and set up sessions
with DAQ systems for ingestion testing.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _find_intan_rhd() -> Path | None:
    """Locate an Intan .rhd example data file.

    Searches several well-known locations used by CI and local development.

    Returns:
        Path to the directory containing .rhd + epochprobemap files,
        or None if no example data can be found.
    """
    candidates = [
        # Explicit env var
        Path(os.environ.get("NDI_EXAMPLE_DATA", "")) / "exp1_eg_saved",
        # CI layout: NDI-matlab checked out beside NDI-python
        Path(__file__).resolve().parents[4]
        / ".."
        / "NDI-matlab"
        / "example_data"
        / "exp1_eg_saved",
        # Home directory
        Path.home() / "ndi_example_data" / "exp1_eg_saved",
        # ndi_common within the package
        Path(__file__).resolve().parents[4]
        / "src"
        / "ndi"
        / "ndi_common"
        / "example_sessions"
        / "exp1_eg_saved",
    ]
    for d in candidates:
        d = d.resolve()
        if d.is_dir() and list(d.glob("*.rhd")):
            return d
    return None


def _find_axon_abf() -> Path | None:
    """Locate an Axon .abf example data file.

    Searches several well-known locations used by CI and local development.

    Returns:
        Path to the directory containing .abf file(s),
        or None if no example data can be found.
    """
    candidates = [
        # Explicit env var
        Path(os.environ.get("NDI_EXAMPLE_DATA", "")) / "axon",
        # CI layout: NDR library example data
        Path(__file__).resolve().parents[4]
        / ".."
        / "NDI-matlab"
        / "tools"
        / "NDR"
        / "example_data",
        # Home directory
        Path.home() / "ndi_example_data" / "axon",
    ]

    # Also try to find NDR's example_data via the installed ndr package
    try:
        from ndr.fun.ndrpath import ndrpath

        ndr_path = Path(ndrpath()) / "example_data"
        candidates.insert(0, ndr_path)
    except Exception:
        pass

    for d in candidates:
        d = d.resolve()
        if d.is_dir() and list(d.glob("*.abf")):
            return d
    return None


def setup_intan_session(session_dir: Path, reader_class: str = "intan") -> dict:
    """Set up a session directory with Intan data for ingestion testing.

    Copies example .rhd file and creates required epochprobemap file.

    Args:
        session_dir: Directory to create the session in.
        reader_class: Either ``"intan"`` for the native reader or
            ``"ndr"`` for the NDR wrapper reader.

    Returns:
        Dict with keys: ``data_dir`` (source dir), ``rhd_file`` (copied file name),
        ``reader_class_str``, ``daqreader_class_str``.

    Raises:
        FileNotFoundError: If no example data could be found.
    """
    data_dir = _find_intan_rhd()
    if data_dir is None:
        raise FileNotFoundError("Intan example data (.rhd) not found")

    # Find the first .rhd file
    rhd_files = sorted(data_dir.glob("*.rhd"))
    rhd_file = rhd_files[0]

    # Copy .rhd to session dir
    shutil.copy2(str(rhd_file), str(session_dir / rhd_file.name))

    # Create epochprobemap file
    stem = rhd_file.stem
    probemap_path = session_dir / f"{stem}.epochprobemap.ndi"
    if not probemap_path.exists():
        probemap_path.write_text(
            "name\treference\ttype\tdevicestring\tsubjectstring\n"
            "ctx\t1\tn-trode\tintan1:ai1\tanteater27@nosuchlab.org\n"
        )

    if reader_class == "intan":
        return {
            "data_dir": data_dir,
            "rhd_file": rhd_file.name,
            "daqreader_class_str": "ndi.daq.reader.mfdaq.intan",
            "reader_class_str": "ndi_daq_reader_mfdaq_intan",
        }
    else:
        return {
            "data_dir": data_dir,
            "rhd_file": rhd_file.name,
            "daqreader_class_str": "ndi.daq.reader.mfdaq.ndr",
            "reader_class_str": "ndi_daq_reader_mfdaq_ndr",
        }


def setup_axon_session(session_dir: Path) -> dict:
    """Set up a session directory with Axon ABF data for ingestion testing.

    Copies example .abf file and creates required epochprobemap file.

    Args:
        session_dir: Directory to create the session in.

    Returns:
        Dict with keys: ``data_dir``, ``abf_file``, ``daqreader_class_str``.

    Raises:
        FileNotFoundError: If no example data could be found.
    """
    data_dir = _find_axon_abf()
    if data_dir is None:
        raise FileNotFoundError("Axon example data (.abf) not found")

    # Find the first .abf file
    abf_files = sorted(data_dir.glob("*.abf"))
    abf_file = abf_files[0]

    # Copy .abf to session dir
    shutil.copy2(str(abf_file), str(session_dir / abf_file.name))

    # Create epochprobemap file
    stem = abf_file.stem
    probemap_path = session_dir / f"{stem}.epochprobemap.ndi"
    if not probemap_path.exists():
        probemap_path.write_text(
            "name\treference\ttype\tdevicestring\tsubjectstring\n"
            "ctx\t1\tn-trode\taxon1:ai1\tanteateri27@nosuchlab.org\n"
        )

    return {
        "data_dir": data_dir,
        "abf_file": abf_file.name,
        "daqreader_class_str": "ndi.daq.reader.mfdaq.ndr",
    }


def delete_raw_files(session_path: Path) -> None:
    """Delete all files in a session directory except the ``.ndi`` database.

    This mirrors the MATLAB ingestion test behavior of removing raw data
    after ingestion so that only the ingested database remains.

    Args:
        session_path: Root directory of the NDI session.
    """
    for item in session_path.iterdir():
        if item.name == ".ndi":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
