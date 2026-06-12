"""
ndi.app.spikesorter - Spike sorting and clustering.

Provides the ndi_app_spikesorter app for clustering extracted spike waveforms
into putative single-neuron units.

MATLAB equivalent: src/ndi/+ndi/+app/spikesorter.m

Porting status (see module-level notes in spike_sort/clusters2neurons):

  * ``check_sorting_parameters`` and ``loadwaveforms`` are fully ported and
    grounded in available ``vlt`` code.
  * ``spike_sort`` is a BLOCKER. Its two MATLAB code paths are both
    non-portable: the graphical path calls
    ``vlt.neuro.spikesorting.cluster_spikewaves_gui`` (an interactive GUI,
    fundamentally not portable to a headless library) and the automatic path
    calls ``klustakwik_cluster`` (a wrapper around the external KlustaKwik
    binary that is absent from the Python ``vlt`` port). The non-interactive
    feature-preparation scaffolding whose dependencies ARE present
    (oversamplespikes / centerspikes_neg / spikewaves2pca) is exposed as the
    private helper :func:`_prepare_waveforms_for_sorting` so the available math
    is exercised, but no automatic clustering algorithm is invented as a
    "faithful" replacement for the GUI/KlustaKwik sorter.
  * ``clusters2neurons`` is BLOCKED downstream of ``spike_sort``: it consumes a
    ``clusterinfo`` array (with per-cluster ``meanshape`` / ``qualitylabel``)
    that only the GUI/KlustaKwik sorter produces. The Python port's
    ``vlt.neuro.spikesorting.cluster_initializeclusterinfo`` takes no arguments
    and returns an empty template, so it cannot reproduce the MATLAB
    ``cluster_initializeclusterinfo(clusterids, waveforms, epochinfo)`` mean
    waveform computation. Faking that computation is not permitted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from . import ndi_app
from .appdoc import ndi_app_appdoc

if TYPE_CHECKING:
    from ..document import ndi_document
    from ..session.session_base import ndi_session


class ndi_app_spikesorter(ndi_app, ndi_app_appdoc):
    """
    ndi_app for clustering spikes into neuron units.

    Takes extracted spike waveforms (from ndi_app_spikeextractor) and
    clusters them into putative single units.

    Doc types:
        - sorting_parameters: Clustering algorithm settings
        - spike_clusters: Cluster assignments and statistics

    Example:
        >>> sorter = ndi_app_spikesorter(session)
        >>> sorter.spike_sort(timeseries_obj, 'default', 'default')

    MATLAB equivalent: ndi.app.spikesorter
    """

    def __init__(self, session: ndi_session | None = None):
        ndi_app.__init__(self, session=session, name="ndi_app_spikesorter")
        ndi_app_appdoc.__init__(
            self,
            doc_types=["sorting_parameters", "spike_clusters"],
            doc_document_types=[
                "apps/spikesorter/sorting_parameters",
                "apps/spikesorter/spike_clusters",
            ],
            doc_session=session,
        )

    @staticmethod
    def default_sorting_parameters() -> dict[str, Any]:
        """Return default sorting parameters.

        Mirrors the field set documented in
        ndi.app.spikesorter/appdoc_description.
        """
        return {
            "graphical_mode": 1,
            "num_pca_features": 10,
            "interpolation": 3,
            "min_clusters": 3,
            "max_clusters": 10,
            "num_start": 5,
        }

    def check_sorting_parameters(
        self,
        sorting_parameters_struct: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Check sorting parameters for validity.

        Given a sorting parameters structure (see appdoc_description), check
        that the parameters are provided and are in appropriate ranges.

        MATLAB equivalent: ndi.app.spikesorter/check_sorting_parameters

        Args:
            sorting_parameters_struct: Input sorting parameters

        Returns:
            The validated sorting parameters structure.

        Raises:
            ValueError: If the required 'interpolation' field is missing.
        """
        # interpolation -- faithful port of the MATLAB clamp to [1, 10].
        if "interpolation" in sorting_parameters_struct:
            interpolation = max(1, round(sorting_parameters_struct["interpolation"]))
            # no interpolation bigger than 10; that's crazy
            interpolation = min(interpolation, 10)
            sorting_parameters_struct["interpolation"] = interpolation
        else:
            raise ValueError("Expected sorting parameters field 'interpolation' is missing.")
        return sorting_parameters_struct

    def loadwaveforms(
        self,
        ndi_timeseries_obj: Any,
        extraction_name: str = "default",
    ) -> tuple[np.ndarray, dict[str, Any], np.ndarray, dict[str, Any], Any, list]:
        """
        Load extracted spike waveforms for an ndi_timeseries_obj.

        Loads extracted spike WAVEFORMS from an ``ndi_timeseries_obj`` with
        extraction name ``extraction_name``.

        MATLAB equivalent: ndi.app.spikesorter/loadwaveforms

        Args:
            ndi_timeseries_obj: Source timeseries element.
            extraction_name: Name of the extraction parameters document.

        Returns:
            Tuple of ``(waveforms, waveformparams, spiketimes, epochinfo,
            extraction_params_doc, waveform_docs)`` where:

            * ``waveforms`` is a ``NumSamples x NumChannels x NumSpikes`` array
              of each spike waveform.
            * ``waveformparams`` is the set of waveform parameters recorded by
              ndi.app.spikeextractor (sample dimensions, sample rate, S0/S1).
            * ``spiketimes`` is the time of each spike waveform (column vector).
            * ``epochinfo`` is a dict with ``EpochStartSamples`` (1-based sample
              index that begins each epoch) and ``EpochNames`` (epoch ids).
            * ``extraction_params_doc`` is the extraction-parameters document.
            * ``waveform_docs`` is the list of per-epoch spikewaves documents.

        Divergence from MATLAB:
            MATLAB delegates per-epoch reads to
            ``ndi.app.spikeextractor.loaddata_appdoc('spikewaves', ...)``. In the
            Python port that extractor method is an unimplemented stub, so this
            method instead reads the ``spikewaves`` documents directly from the
            database (matching on element_id + extraction_parameters_id +
            epoch_id) and decodes the attached ``spikewaves.vsw`` /
            ``spiketimes.bin`` binaries with
            :mod:`ndi.util.vhlspikewaveformfile` (a MATLAB-byte-compatible port
            of ``vlt.file.custom_file_formats``). The returned values are
            equivalent.

        Raises:
            RuntimeError: If the session is unset or the extraction parameters
                document cannot be found.
        """
        if self._session is None:
            raise RuntimeError("ndi_app_spikesorter.loadwaveforms requires a session.")

        # Read spikewaves.vsw with NDI's vhlspikewaveformfile reader (a port of
        # vlt.file.custom_file_formats.readvhlspikewaveformfile; byte-compatible
        # with MATLAB, no vlt dependency).
        from ..query import ndi_query
        from ..util.vhlspikewaveformfile import (
            read_vhlspikewaveformfile as readvhlspikewaveformfile,
        )

        waveforms = None
        spiketimes_list: list[np.ndarray] = []
        waveformparams: dict[str, Any] = {}
        epochinfo: dict[str, Any] = {"EpochStartSamples": [], "EpochNames": []}
        waveform_docs: list = []

        # Locate the extraction parameters document by name.
        extraction_params_doc = self._find_extraction_parameters_doc(extraction_name)
        if extraction_params_doc is None:
            raise RuntimeError(
                f"Could not load extraction parameters document with name " f"'{extraction_name}'."
            )

        element_id = ndi_timeseries_obj.id
        extraction_id = extraction_params_doc.id

        et = ndi_timeseries_obj.epochtable()

        sample_counter = 0
        for entry in et:
            epoch_id = entry.get("epoch_id", "") if isinstance(entry, dict) else entry.epoch_id
            epochinfo["EpochStartSamples"].append(sample_counter + 1)  # 1-based, as MATLAB
            epochinfo["EpochNames"].append(epoch_id)

            # Find the spikewaves doc for this element/extraction/epoch.
            q = (
                ndi_query("").isa("spikewaves")
                & ndi_query("").depends_on("element_id", element_id)
                & ndi_query("").depends_on("extraction_parameters_id", extraction_id)
                & (ndi_query("epochid.epochid") == epoch_id)
            )
            docs = self._session.database_search(q)
            if not docs:
                # No spikes extracted for this epoch; skip it like an empty read.
                continue
            sw_doc = docs[0]
            waveform_docs.append(sw_doc)

            waveshere, waveformparams = self._read_spikewaves_binary(
                sw_doc, readvhlspikewaveformfile
            )
            spiketimes_here = self._read_spiketimes_binary(sw_doc)

            if waveshere is None or waveshere.size == 0:
                continue

            if waveforms is None:
                waveforms = waveshere
            else:
                # Concatenate along the spike axis (axis=2: Samples x Chans x Spikes).
                waveforms = np.concatenate([waveforms, waveshere], axis=2)

            spiketimes_list.append(np.asarray(spiketimes_here, dtype=float).reshape(-1))
            sample_counter += int(waveshere.shape[2])

        if waveforms is None:
            waveforms = np.empty((0, 0, 0))
        if spiketimes_list:
            spiketimes = np.concatenate(spiketimes_list).reshape(-1, 1)
        else:
            spiketimes = np.empty((0, 1))

        return (
            waveforms,
            waveformparams,
            spiketimes,
            epochinfo,
            extraction_params_doc,
            waveform_docs,
        )

    def _find_extraction_parameters_doc(self, extraction_name: str) -> Any:
        """Find the extraction parameters document with the given name."""
        from ..query import ndi_query

        q = ndi_query("").isa("extraction_parameters") & (ndi_query("base.name") == extraction_name)
        docs = self._session.database_search(q)
        if not docs:
            return None
        return docs[0]

    def _read_spikewaves_binary(
        self,
        sw_doc: Any,
        readvhlspikewaveformfile: Any,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Decode the ``spikewaves.vsw`` binary attached to a spikewaves doc.

        Uses the available ``vlt.file.custom_file_formats.readvhlspikewaveformfile``
        reader, which returns ``(waveforms, waveparameters)`` where ``waveforms``
        is ``NumSamples x NumChannels x NumSpikes`` and ``waveparameters`` carries
        the sample geometry (S0, S1, samplerate, ...).
        """
        fobj = self._session.database_openbinarydoc(sw_doc, "spikewaves.vsw")
        try:
            result = readvhlspikewaveformfile(fobj)
        finally:
            self._session.database_closebinarydoc(fobj)
        # The vlt reader returns (waveforms, waveparameters).
        if isinstance(result, tuple):
            waves = np.asarray(result[0])
            params = result[1] if len(result) > 1 else {}
        else:
            waves = np.asarray(result)
            params = {}
        if not isinstance(params, dict):
            # Normalise a struct-like object to a plain dict for the caller.
            params = {
                k: getattr(params, k)
                for k in dir(params)
                if not k.startswith("_") and not callable(getattr(params, k))
            }
        return waves, params

    def _read_spiketimes_binary(self, sw_doc: Any) -> np.ndarray:
        """Decode the ``spiketimes.bin`` (float64) binary of a spikewaves doc."""
        exists, _ = self._session.database_existbinarydoc(sw_doc, "spiketimes.bin")
        if not exists:
            return np.empty((0,), dtype=float)
        fobj = self._session.database_openbinarydoc(sw_doc, "spiketimes.bin")
        try:
            raw = fobj.read()
        finally:
            self._session.database_closebinarydoc(fobj)
        # spiketimes.bin is float32 (MATLAB fwrite(...,'float32'); spikeextractor
        # writes "<f4"). Reading it as float64 would mis-decode every value.
        return np.frombuffer(raw, dtype="<f4").astype(float)

    @staticmethod
    def _prepare_waveforms_for_sorting(
        waveforms: np.ndarray,
        waveformparameters: dict[str, Any],
        sorting_parameters_struct: dict[str, Any],
        threshold_sign: int = -1,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Run the non-interactive waveform preparation shared by both sort paths.

        This reproduces the MATLAB ``spike_sort`` pre-clustering steps whose vlt
        dependencies ARE present in the Python port -- oversampling by spline
        interpolation, re-centering on the spike extremum, and PCA feature
        extraction -- WITHOUT performing any clustering (which is blocked, see
        the module docstring).

        MATLAB equivalent: the ``oversamplespikes`` / ``centerspikes_neg`` /
        ``spikewaves2pca`` block inside ndi.app.spikesorter/spike_sort.

        Args:
            waveforms: ``NumSamples x NumChannels x NumSpikes`` waveform array.
            waveformparameters: Extraction waveform parameters (needs ``S0``/``S1``).
            sorting_parameters_struct: Validated sorting parameters
                (uses ``interpolation`` and ``num_pca_features``).
            threshold_sign: Sign of the extraction threshold (waveform_sign is
                its negation, as in MATLAB).

        Returns:
            Tuple ``(waveforms_prepared, wavesamples, features)`` where
            ``waveforms_prepared`` is ``NumSamples x NumChannels x NumSpikes``,
            ``wavesamples`` is the (possibly oversampled) sample-index axis, and
            ``features`` is the ``NumSpikes x num_pca_features`` PCA feature matrix.

        Confidence: MEDIUM -- exercises real vlt functions; flagged for review.
        """
        from vlt.neuro.spikesorting import (
            centerspikes_neg,
            oversamplespikes,
            spikewaves2pca,
        )

        s0 = int(waveformparameters.get("S0", waveformparameters.get("s0", 0)))
        s1 = int(waveformparameters.get("S1", waveformparameters.get("s1", waveforms.shape[0] - 1)))
        wavesamples = np.arange(s0, s1 + 1)

        prepared = waveforms
        if int(sorting_parameters_struct.get("interpolation", 1)) > 1:
            # MATLAB permutes to [Spikes x Samples x Channels] for vlt calls.
            permuted = np.transpose(waveforms, (2, 0, 1))
            # oversamplespikes returns (spikeshapesup, tup) when t is given.
            permuted, wavesamples = oversamplespikes(
                permuted, int(sorting_parameters_struct["interpolation"]), wavesamples
            )
            permuted = np.asarray(permuted)
            waveform_sign = -1 * int(threshold_sign)
            # centerspikes_neg returns (centeredspikes, shifts).
            centered, _shifts = centerspikes_neg(waveform_sign * permuted, 10)
            permuted = waveform_sign * np.asarray(centered)
            # Permute back to [Samples x Channels x Spikes].
            prepared = np.transpose(permuted, (1, 2, 0))

        features = spikewaves2pca(prepared, int(sorting_parameters_struct["num_pca_features"]))
        return prepared, np.asarray(wavesamples), np.asarray(features)

    def spike_sort(
        self,
        ndi_timeseries_obj: Any,
        extraction_name: str = "default",
        sorting_parameters_name: str = "default",
        redo: bool = False,
    ) -> list[ndi_document]:
        """
        Sort spikes from a timeseries element into clusters.

        MATLAB equivalent: ndi.app.spikesorter/spike_sort

        Args:
            ndi_timeseries_obj: Source timeseries element.
            extraction_name: Name of the extraction parameters document.
            sorting_parameters_name: Name of the sorting parameters document.
            redo: Re-sort even if results exist.

        Returns:
            List of spike_clusters documents.

        Raises:
            NotImplementedError: Always. Both MATLAB sorting paths are
                non-portable -- see the module docstring. Use
                :func:`loadwaveforms` to read extracted waveforms and
                :func:`_prepare_waveforms_for_sorting` to run the available
                oversample/center/PCA feature scaffolding.
        """
        raise NotImplementedError(
            "ndi.app.spikesorter.spike_sort is not portable to a headless library. "
            "The graphical path requires vlt.neuro.spikesorting.cluster_spikewaves_gui, "
            "an INTERACTIVE GUI that cannot run headless; the automatic path requires "
            "klustakwik_cluster (a wrapper around the external KlustaKwik binary) which "
            "is absent from the Python vlt port. No automatic clustering algorithm is "
            "substituted, as that would not be a faithful port. Available, grounded "
            "scaffolding is exposed via loadwaveforms() and "
            "_prepare_waveforms_for_sorting()."
        )

    def clusters2neurons(
        self,
        ndi_timeseries_obj: Any,
        sorting_parameters_name: str = "default",
        extraction_parameters_name: str = "default",
        redo: bool = False,
    ) -> None:
        """
        Create ndi.neuron objects from spike clusterings.

        Generates ndi.neuron objects for each spike cluster represented in the
        spike_clusters document.

        MATLAB equivalent: ndi.app.spikesorter/clusters2neurons

        Args:
            ndi_timeseries_obj: Source timeseries element.
            sorting_parameters_name: Name of the sorting parameters document.
            extraction_parameters_name: Name of the extraction parameters document.
            redo: Re-create even if neurons exist.

        Raises:
            NotImplementedError: Always. This method consumes the per-cluster
                ``clusterinfo`` (mean waveforms + quality labels) that only the
                blocked :func:`spike_sort` produces. The Python port's
                ``vlt.neuro.spikesorting.cluster_initializeclusterinfo`` takes no
                arguments and returns an empty template, so the MATLAB
                ``cluster_initializeclusterinfo(clusterids, waveforms, epochinfo)``
                mean-waveform computation cannot be reproduced. It is therefore
                blocked downstream of spike_sort.
        """
        raise NotImplementedError(
            "ndi.app.spikesorter.clusters2neurons is blocked downstream of spike_sort: "
            "it requires a spike_clusters document whose clusterinfo (per-cluster "
            "meanshape + qualitylabel) is produced only by the non-portable GUI / "
            "KlustaKwik sorter. The Python vlt port's cluster_initializeclusterinfo() "
            "takes no arguments and returns an empty template, so MATLAB's "
            "cluster_initializeclusterinfo(clusterids, waveforms, epochinfo) mean-"
            "waveform computation cannot be reproduced. See spike_sort()."
        )

    # ------------------------------------------------------------------
    # FUNCTIONS THAT OVERRIDE NDI.APP.APPDOC
    # ------------------------------------------------------------------

    def struct2doc(self, appdoc_type: str, appdoc_struct: dict, *args, **kwargs) -> ndi_document:
        """
        Create an ndi.document from an input structure and parameters.

        MATLAB equivalent: ndi.app.spikesorter/struct2doc

        For ndi.app.spikesorter, ``appdoc_type`` may be:

        ===================== =================================================
        APPDOC_TYPE           Description
        ===================== =================================================
        'sorting_parameters'  Parameters used to guide the sorting.
        'spike_clusters'      Created internally by spike_sort (raises here).
        ===================== =================================================

        Args:
            appdoc_type: The appdoc type.
            appdoc_struct: The structure to store.
            *args: For 'sorting_parameters', the first positional argument is the
                sorting parameters name (string).

        Returns:
            The created ndi.document.
        """
        from ..document import ndi_document

        if appdoc_type == "sorting_parameters":
            sorting_name = kwargs.get("sorting_parameters_name")
            if sorting_name is None and args:
                sorting_name = args[0]
            if sorting_name is None:
                raise ValueError(
                    "Needs an additional argument describing the sorting parameters name."
                )
            if not isinstance(sorting_name, str):
                raise ValueError("sorting parameters name must be a character string.")
            doc = ndi_document(
                "apps/spikesorter/sorting_parameters",
                **{"sorting_parameters": appdoc_struct, "base.name": sorting_name},
            )
            if self._session is not None:
                doc.set_session_id(self._session.id())
            return doc
        elif appdoc_type == "spike_clusters":
            raise ValueError("spike_clusters documents are created internally.")
        else:
            raise ValueError(f"Unknown APPDOC_TYPE {appdoc_type}.")

    def isvalid_appdoc_struct(self, appdoc_type: str, appdoc_struct: dict) -> tuple[bool, str]:
        """
        Check whether an input structure is a valid descriptor for an APPDOC.

        MATLAB equivalent: ndi.app.spikesorter/isvalid_appdoc_struct

        Args:
            appdoc_type: 'sorting_parameters' or 'spike_clusters'.
            appdoc_struct: The structure to validate.

        Returns:
            Tuple of ``(is_valid, error_message)``.
        """
        if appdoc_type == "sorting_parameters":
            fields_needed = [
                "graphical_mode",
                "num_pca_features",
                "interpolation",
                "min_clusters",
                "max_clusters",
                "num_start",
            ]
            return self._has_all_fields(appdoc_struct, fields_needed)
        elif appdoc_type == "spike_clusters":
            fields_needed = ["epoch_info", "clusterinfo"]
            return self._has_all_fields(appdoc_struct, fields_needed)
        else:
            raise ValueError(f"Unknown appdoc_type {appdoc_type}.")

    @staticmethod
    def _has_all_fields(variable: dict, field_names: list[str]) -> tuple[bool, str]:
        """Check that ``variable`` contains every key in ``field_names``.

        A vlt-free port of the field-presence half of ``vlt.data.hasAllFields``
        (the size checks MATLAB performs are not load-bearing for these
        appdoc structs). The error message format -- ``"'<field>' not
        present."`` for the first missing field -- matches vlt exactly, so
        validation and ``struct2doc`` work without vlt on the import path.
        """
        for field_name in field_names:
            if field_name not in variable:
                return False, f"'{field_name}' not present."
        return True, ""

    def find_appdoc(self, appdoc_type: str, *args, **kwargs) -> list[ndi_document]:
        """
        Find an appdoc document in the session database.

        MATLAB equivalent: ndi.app.spikesorter/find_appdoc

        For 'sorting_parameters', the first positional argument is the sorting
        parameters name. For 'spike_clusters', the positional arguments are
        ``(ndi_timeseries_obj, extraction_name, sorting_parameters_name)``.

        Args:
            appdoc_type: 'sorting_parameters' or 'spike_clusters'.

        Returns:
            List of matching ndi.documents.
        """
        if self._session is None:
            return []
        from ..query import ndi_query

        kind = appdoc_type.lower()
        if kind == "sorting_parameters":
            sorting_parameters_name = kwargs.get("sorting_parameters_name")
            if sorting_parameters_name is None and args:
                sorting_parameters_name = args[0]
            q = (ndi_query("base.name") == sorting_parameters_name) & ndi_query("").isa(
                "sorting_parameters"
            )
            return self._session.database_search(q)
        elif kind == "spike_clusters":
            if len(args) < 3:
                raise ValueError(
                    "find_appdoc('spike_clusters', ...) requires "
                    "(ndi_timeseries_obj, extraction_name, sorting_parameters_name)."
                )
            ndi_timeseries_obj, extraction_name, sorting_parameters_name = args[:3]

            extraction_parameters_doc = self._find_extraction_parameters_doc(extraction_name)
            if extraction_parameters_doc is None:
                return []

            sorting_parameters_doc = self.find_appdoc("sorting_parameters", sorting_parameters_name)
            if not sorting_parameters_doc:
                return []
            sorting_parameters_doc = sorting_parameters_doc[0]

            q = (
                ndi_query("").isa("spike_clusters")
                & ndi_query("").depends_on("element_id", ndi_timeseries_obj.id)
                & ndi_query("").depends_on("sorting_parameters_id", sorting_parameters_doc.id)
                & ndi_query("").depends_on("extraction_parameters_id", extraction_parameters_doc.id)
            )
            return self._session.database_search(q)
        else:
            raise ValueError(f"Unknown APPDOC_TYPE {appdoc_type}.")

    def loaddata_appdoc(self, appdoc_type: str, *args, **kwargs) -> Any:
        """
        Load data from an application document.

        MATLAB equivalent: ndi.app.spikesorter/loaddata_appdoc

        For 'sorting_parameters' this returns the matching documents. For
        'spike_clusters' this returns ``(clusterids, spike_clusters_doc)`` where
        ``clusterids`` is the per-spike cluster assignment array decoded from the
        ``spike_cluster.bin`` (uint16) binary.

        Args:
            appdoc_type: 'sorting_parameters' or 'spike_clusters'.

        Returns:
            For 'sorting_parameters': list of documents.
            For 'spike_clusters': tuple ``(clusterids, spike_clusters_doc)`` or
            ``(None, None)`` if no document is found.
        """
        kind = appdoc_type.lower()
        if kind == "sorting_parameters":
            return self.find_appdoc(appdoc_type, *args, **kwargs)
        elif kind == "spike_clusters":
            docs = self.find_appdoc(appdoc_type, *args, **kwargs)
            if not docs:
                return None, None
            if len(docs) > 1:
                raise RuntimeError("Too many spike clusters docs found!")
            spike_clusters_doc = docs[0]
            fobj = self._session.database_openbinarydoc(spike_clusters_doc, "spike_cluster.bin")
            try:
                raw = fobj.read()
            finally:
                self._session.database_closebinarydoc(fobj)
            clusterids = np.frombuffer(raw, dtype="<u2").astype(np.uint16)
            return clusterids, spike_clusters_doc
        else:
            raise ValueError(f"Unknown APPDOC_TYPE {appdoc_type}.")

    def __repr__(self) -> str:
        return f"ndi_app_spikesorter(session={self._session is not None})"
