"""
ndi.app.spikesorter - Spike sorting and clustering.

Provides the ndi_app_spikesorter app for clustering extracted spike waveforms
into putative single-neuron units.

MATLAB equivalent: src/ndi/+ndi/+app/spikesorter.m

Porting status:

  * ``check_sorting_parameters`` and ``loadwaveforms`` are fully ported and
    grounded in available ``vlt`` code.
  * ``spike_sort`` implements the AUTOMATIC (non-graphical) sorting path. It runs
    the available pre-clustering scaffolding (oversamplespikes / centerspikes_neg
    / spikewaves2pca, via :func:`_prepare_waveforms_for_sorting`) and then
    clusters the PCA features with :mod:`ndi.util.klustakwik`, a wrapper around
    the optional ``klustakwik2`` package. The MATLAB automatic path calls
    ``klustakwik_cluster`` (a wrapper around the *external* classic KlustaKwik
    binary); ``klustakwik2`` is a maintained Python port of the masked KlustaKwik
    algorithm. On the dense PCA features used here it behaves as a classic-style
    CEM, but it is NOT bit-identical to the MATLAB binary and clustering is
    stochastic -- see :mod:`ndi.util.klustakwik`. The GRAPHICAL path
    (``graphical_mode=1``) is the interactive ``cluster_spikewaves_gui`` editor,
    delivered separately as a PyQt application; ``spike_sort`` raises a clear
    error directing graphical callers there.
  * ``clusters2neurons`` is fully ported: it reads the ``spike_clusters``
    document, keeps clusters whose ``qualitylabel`` marks them as usable, and
    creates an :class:`ndi.neuron` element plus a ``neuron_extracellular``
    document (with the cluster mean waveform) and per-epoch spike trains for
    each. A pure automatic sort labels every cluster ``'Unselected'`` (as in
    MATLAB), so neurons are produced only after the clusters are curated (by the
    graphical editor) to mark units ``Good`` / ``Excellent`` / ``Multi-unit``.
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
        if isinstance(et, tuple):  # epochtable() returns (table, hash)
            et = et[0]

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
        """Find the extraction parameters document with the given name.

        The extractor stores these as ``spike_extraction_parameters`` documents
        (class name from apps/spikeextractor/spike_extraction_parameters.json);
        ``isa('extraction_parameters')`` would never match, so we query the real
        class name -- matching ndi.app.spikeextractor.find_appdoc.
        """
        from ..query import ndi_query

        q = ndi_query("").isa("spike_extraction_parameters") & (
            ndi_query("base.name") == extraction_name
        )
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

    @staticmethod
    def cluster_initializeclusterinfo(
        clusterids: np.ndarray,
        waveforms: np.ndarray,
        epochinfo: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Build the per-cluster ``clusterinfo`` array for a clustering.

        Port of MATLAB ``vlt.neuro.spikesorting.cluster_initializeclusterinfo``
        (the ``InitClusterInfo`` computation in ``cluster_spikewaves_gui.m``); the
        Python ``vlt`` port ships only a no-argument stub. For each distinct
        cluster id it records the cluster number, an initial ``'Unselected'``
        quality label, the spike count, and the mean waveform across that
        cluster's spikes.

        Args:
            clusterids: length-NumSpikes array of (1-based) cluster numbers.
            waveforms: ``NumSamples x NumChannels x NumSpikes`` waveform array
                (the prepared/oversampled waveforms the clustering ran on).
            epochinfo: dict with ``EpochNames`` (used for ``EpochStart`` /
                ``EpochStop``, the first and last epoch ids).

        Returns:
            A list of dicts, one per cluster, with keys ``number`` (str),
            ``qualitylabel`` (``'Unselected'``), ``number_of_spikes`` (int),
            ``meanshape`` (``NumSamples x NumChannels`` nested list),
            ``EpochStart`` and ``EpochStop`` (epoch ids).
        """
        clusterids = np.asarray(clusterids).ravel()
        epoch_names = []
        if isinstance(epochinfo, dict):
            epoch_names = list(epochinfo.get("EpochNames", []) or [])
        epoch_start = epoch_names[0] if epoch_names else ""
        epoch_stop = epoch_names[-1] if epoch_names else ""

        n_samples = int(waveforms.shape[0]) if waveforms.ndim == 3 else 0
        n_channels = int(waveforms.shape[1]) if waveforms.ndim == 3 else 0

        clusterinfo: list[dict[str, Any]] = []
        for c in np.unique(clusterids):
            idx = np.flatnonzero(clusterids == c)
            if idx.size and waveforms.ndim == 3 and waveforms.shape[2] >= idx.max() + 1:
                meanshape = np.nanmean(waveforms[:, :, idx], axis=2)
            else:
                meanshape = np.zeros((n_samples, n_channels))
            clusterinfo.append(
                {
                    "number": str(int(c)),
                    "qualitylabel": "Unselected",
                    "number_of_spikes": int(idx.size),
                    "meanshape": np.asarray(meanshape, dtype=float).tolist(),
                    "EpochStart": epoch_start,
                    "EpochStop": epoch_stop,
                }
            )
        return clusterinfo

    def spike_sort(
        self,
        ndi_timeseries_obj: Any,
        extraction_name: str = "default",
        sorting_parameters_name: str = "default",
        redo: bool = False,
    ) -> list[ndi_document]:
        """
        Sort spikes from a timeseries element into clusters (automatic path).

        Runs the automatic (non-graphical) KlustaKwik-style sorter: load the
        extracted waveforms, prepare PCA features, cluster them with
        :mod:`ndi.util.klustakwik`, and store a ``spike_clusters`` document with
        the per-spike cluster assignment (``spike_cluster.bin``, ``uint16``) and a
        ``clusterinfo`` array of per-cluster mean waveforms.

        MATLAB equivalent: ndi.app.spikesorter/spike_sort

        Args:
            ndi_timeseries_obj: Source timeseries element.
            extraction_name: Name of the extraction parameters document.
            sorting_parameters_name: Name of the sorting parameters document.
            redo: Re-sort even if results exist (removes the old document first).

        Returns:
            A one-element list with the ``spike_clusters`` document.

        Raises:
            RuntimeError: If the session is unset.
            ValueError: If the sorting parameters document is missing.
            NotImplementedError: If ``graphical_mode`` is set -- the interactive
                editor ships as a separate PyQt application; set
                ``graphical_mode=0`` to use this automatic path.
            ImportError: If ``graphical_mode=0`` but the optional ``klustakwik2``
                dependency is not installed (see :mod:`ndi.util.klustakwik`).
        """
        if self._session is None:
            raise RuntimeError("ndi_app_spikesorter.spike_sort requires a session.")

        from ..document import ndi_document

        # Step 1a: get the sorting_parameters document.
        sorting_parameters_doc = self.find_appdoc("sorting_parameters", sorting_parameters_name)
        if len(sorting_parameters_doc) == 0:
            raise ValueError(
                "No spike sorting parameters document with name "
                f"'{sorting_parameters_name}' was found."
            )
        if len(sorting_parameters_doc) > 1:
            raise RuntimeError(
                "Too many spike sorting parameters documents with name "
                f"'{sorting_parameters_name}' were found."
            )
        sorting_parameters_doc = sorting_parameters_doc[0]
        sorting_parameters_struct = self.check_sorting_parameters(
            dict(sorting_parameters_doc.document_properties.get("sorting_parameters", {}))
        )

        # Step 1b: if a cluster document already exists, return it (or redo).
        existing = self.find_appdoc(
            "spike_clusters", ndi_timeseries_obj, extraction_name, sorting_parameters_name
        )
        if len(existing) == 1 and not redo:
            return [existing[0]]
        if redo and existing:
            self._session.database_rm(existing)

        # Step 1c: gather the extracted waveforms across epochs.
        (
            waveforms,
            waveformparameters,
            spiketimes,
            epochinfo,
            extract_doc,
            waveform_docs,
        ) = self.loadwaveforms(ndi_timeseries_obj, extraction_name)

        # Step 2: prepare features and cluster.
        if int(sorting_parameters_struct.get("graphical_mode", 0)):
            raise NotImplementedError(
                "Graphical spike sorting (graphical_mode=1) is the interactive "
                "cluster_spikewaves_gui editor, delivered as a separate PyQt "
                "application. Set graphical_mode=0 to use the automatic sorter here."
            )

        ext_params = extract_doc.document_properties.get("spike_extraction_parameters", {})
        threshold_sign = int(ext_params.get("threshold_sign", -1))
        prepared, wavesamples, features = self._prepare_waveforms_for_sorting(
            waveforms, waveformparameters, sorting_parameters_struct, threshold_sign=threshold_sign
        )

        from ..util.klustakwik import cluster_spikewaves

        # _prepare_waveforms_for_sorting returns features as NumFeatures x NumSpikes
        # (spikewaves2pca's orientation); KlustaKwik wants one row per spike.
        clusterids, _numclusters = cluster_spikewaves(
            np.asarray(features).T,
            min_clusters=int(sorting_parameters_struct.get("min_clusters", 3)),
            max_clusters=int(sorting_parameters_struct.get("max_clusters", 10)),
            num_start=int(sorting_parameters_struct.get("num_start", 5)),
        )
        clusterinfo = self.cluster_initializeclusterinfo(clusterids, prepared, epochinfo)

        # Step 3: build and store the spike_clusters document.
        spike_clusters = {
            "epoch_info": epochinfo,
            "clusterinfo": clusterinfo,
            "waveform_sample_times": np.asarray(wavesamples, dtype=float).ravel().tolist(),
        }
        doc = ndi_document("apps/spikesorter/spike_clusters", **{"spike_clusters": spike_clusters})
        doc = doc.set_session_id(self._session.id())
        doc = doc.set_dependency_value(
            "element_id", ndi_timeseries_obj.id, error_if_not_found=False
        )
        doc = doc.set_dependency_value(
            "sorting_parameters_id", sorting_parameters_doc.id, error_if_not_found=False
        )
        doc = doc.set_dependency_value(
            "extraction_parameters_id", extract_doc.id, error_if_not_found=False
        )
        for wd in waveform_docs:
            doc = doc.add_dependency_value_n("spikewaves_doc_id", wd.id)

        # spike_cluster.bin: per-spike cluster id as uint16 (MATLAB fwrite uint16).
        import tempfile
        from pathlib import Path

        tmpdir = Path(tempfile.mkdtemp(prefix="ndi_spikeclusters_"))
        bin_path = tmpdir / "spike_cluster.bin"
        with open(bin_path, "wb") as fh:
            fh.write(np.asarray(clusterids, dtype="<u2").tobytes())
        doc = doc.add_file("spike_cluster.bin", str(bin_path))

        self._session.database_add(doc)
        return [doc]

    # Mapping from cluster quality label to the MATLAB quality_number, and the
    # set of labels that yield a neuron (quality_number in 1..4). Mirrors the
    # switch in ndi.app.spikesorter/clusters2neurons.
    _QUALITY_NUMBER = {
        "unselected": -1,
        "not useable": 5,
        "multi-unit": 3,
        "good": 2,
        "excellent": 1,
    }

    def clusters2neurons(
        self,
        ndi_timeseries_obj: Any,
        sorting_parameters_name: str = "default",
        extraction_parameters_name: str = "default",
        redo: bool = False,
    ) -> list[Any]:
        """
        Create ndi.neuron objects from spike clusterings.

        Generates an :class:`ndi.neuron` element for each usable spike cluster in
        the ``spike_clusters`` document -- those whose ``qualitylabel`` maps to a
        quality number in 1..4 (``Excellent`` / ``Good`` / ``Multi-unit``). Each
        neuron gets a ``neuron_extracellular`` document (cluster mean waveform and
        quality) and per-epoch spike trains. Clusters labelled ``Unselected`` or
        ``Not useable`` are skipped, so a freshly (automatically) sorted document
        -- whose clusters are all ``Unselected`` -- yields no neurons until the
        clusters are curated.

        MATLAB equivalent: ndi.app.spikesorter/clusters2neurons

        Args:
            ndi_timeseries_obj: Source timeseries element.
            sorting_parameters_name: Name of the sorting parameters document.
            extraction_parameters_name: Name of the extraction parameters document.
            redo: Re-create even if neurons exist (removes the old neuron
                elements first).

        Returns:
            The list of created ``neuron_extracellular`` documents (empty if no
            cluster is usable). The neuron elements, their epoch documents, and
            these documents are all committed to the database.
        """
        if self._session is None:
            raise RuntimeError("ndi_app_spikesorter.clusters2neurons requires a session.")

        from ..element_timeseries import ndi_element_timeseries
        from ..query import ndi_query
        from ..time.clocktype import ndi_time_clocktype

        # find_appdoc('spike_clusters', ...) order is (obj, extraction, sorting).
        clusterids, spike_clusters_doc = self.loaddata_appdoc(
            "spike_clusters",
            ndi_timeseries_obj,
            extraction_parameters_name,
            sorting_parameters_name,
        )
        if spike_clusters_doc is None:
            return []
        clusterids = np.asarray(clusterids).ravel()

        # Existing neurons for this clustering?
        q_n = ndi_query("").isa("neuron_extracellular") & ndi_query("").depends_on(
            "spike_clusters_id", spike_clusters_doc.id
        )
        anyneurons = self._session.database_search(q_n)
        if anyneurons and not redo:
            return []
        if anyneurons and redo:
            # Remove the neuron elements those neuron_extracellular docs point at
            # (and their epoch documents), then the neuron docs themselves. Mirror
            # ndi.fun.probe.import.kilosort.removeold: ndi_query does not compose an
            # OR of a base.id match with a depends_on clause, so run the two halves
            # separately and union them.
            for ndoc in anyneurons:
                element_id = ndoc.dependency_value("element_id", error_if_not_found=False)
                if not element_id:
                    continue
                elem_docs = self._session.database_search(ndi_query("base.id") == element_id)
                dep_docs = self._session.database_search(
                    ndi_query("").depends_on("element_id", element_id)
                )
                seen = {d.id for d in elem_docs}
                elem_docs = elem_docs + [d for d in dep_docs if d.id not in seen]
                if elem_docs:
                    self._session.database_rm(elem_docs)
            self._session.database_rm(anyneurons)

        # Re-load the waveforms to recover spike times and the epoch partition.
        (
            _waveforms,
            _waveformparams,
            spiketimes,
            epochinfo,
            _extract_doc,
            _waveform_docs,
        ) = self.loadwaveforms(ndi_timeseries_obj, extraction_parameters_name)
        spiketimes = np.asarray(spiketimes, dtype=float).ravel()

        et = ndi_timeseries_obj.epochtable()
        if isinstance(et, tuple):  # epochtable() returns (table, hash)
            et = et[0]
        epoch_ids = [(e.get("epoch_id", "") if isinstance(e, dict) else e.epoch_id) for e in et]

        sc = spike_clusters_doc.document_properties.get("spike_clusters", {})
        clusterinfo = sc.get("clusterinfo", []) or []
        waveform_sample_times = sc.get("waveform_sample_times", []) or []

        # Concatenated-spike-index boundaries per epoch (1-based start of each
        # epoch from loadwaveforms; the final boundary is one past the last
        # spike). NOTE: MATLAB used numel(spiketimes)-1 as the final boundary,
        # which drops the last spikes of the last epoch; we use the inclusive
        # total so every spike is assigned to its epoch.
        epoch_starts = list(epochinfo.get("EpochStartSamples", []) or [])
        boundaries = [int(s) for s in epoch_starts] + [int(spiketimes.size) + 1]

        # App provenance for the neuron documents (MATLAB passes 'app', appstruct).
        app_struct = self.newdocument().document_properties.get("app", {})

        specs: list[dict[str, Any]] = []
        neuron_docs: list[Any] = []
        clock = ndi_time_clocktype("dev_local_time")
        for n, ci in enumerate(clusterinfo):
            label = str(ci.get("qualitylabel", "Unselected"))
            if label.lower() in ("unselected", "not useable"):
                continue
            value = self._QUALITY_NUMBER.get(label.lower(), -1)
            if not (0 < value <= 4):  # only reasonable neurons
                continue

            clusternum = n + 1  # 1-based, matching the contiguous cluster ids
            meanshape = np.asarray(ci.get("meanshape", []), dtype=float)
            n_samp = int(meanshape.shape[0]) if meanshape.ndim == 2 else 0
            n_chan = int(meanshape.shape[1]) if meanshape.ndim == 2 else 0

            ne = {
                "number_of_samples_per_channel": n_samp,
                "number_of_channels": n_chan,
                "mean_waveform": meanshape.tolist(),
                "waveform_sample_times": list(waveform_sample_times),
                "cluster_index": clusternum,
                "quality_number": int(value),
                "quality_label": label,
            }
            from ..document import ndi_document

            neuron_fields: dict[str, Any] = {"neuron_extracellular": ne}
            for k, v in app_struct.items():
                neuron_fields[f"app.{k}"] = v
            neuron_doc = ndi_document("neuron/neuron_extracellular", **neuron_fields)
            neuron_doc.set_session_id(self._session.id())
            neuron_doc.set_dependency_value("spike_clusters_id", spike_clusters_doc.id)
            neuron_docs.append(neuron_doc)

            # Spike trains for this cluster, one entry per epoch in the cluster's
            # EpochStart..EpochStop range (all epochs after an automatic sort).
            spike_indexes = np.flatnonzero(clusterids == clusternum)
            start_id = ci.get("EpochStart", epoch_ids[0] if epoch_ids else "")
            stop_id = ci.get("EpochStop", epoch_ids[-1] if epoch_ids else "")
            j0 = epoch_ids.index(start_id) if start_id in epoch_ids else 0
            j1 = epoch_ids.index(stop_id) if stop_id in epoch_ids else len(epoch_ids) - 1

            epochs: list[dict[str, Any]] = []
            for j in range(j0, j1 + 1):
                entry = et[j]
                t0_t1 = entry.get("t0_t1") if isinstance(entry, dict) else entry.t0_t1
                first_pair = t0_t1[0] if isinstance(t0_t1, list) and t0_t1 else t0_t1
                lo = boundaries[j]
                hi = boundaries[j + 1] if j + 1 < len(boundaries) else int(spiketimes.size) + 1
                # 1-based inclusive concatenated spike indices within this epoch.
                here = spike_indexes[(spike_indexes >= lo - 1) & (spike_indexes < hi - 1)]
                times = spiketimes[here] if here.size else np.zeros((0,))
                epochs.append(
                    {
                        "epoch_id": epoch_ids[j],
                        "epoch_clock": clock,
                        "t0_t1": list(first_pair),
                        "timepoints": np.asarray(times, dtype=float),
                        "datapoints": np.ones(times.shape[0], dtype=float),
                    }
                )

            specs.append(
                {
                    "name": f"{ndi_timeseries_obj.name}_{clusternum}",
                    "reference": int(getattr(ndi_timeseries_obj, "reference", 0) or 0),
                    "type": "spikes",
                    "epochs": epochs,
                    "extra_documents": [neuron_doc],
                }
            )

        if not specs:
            return []
        # build_objects=False: commit the element / epoch / neuron_extracellular
        # documents without constructing the ndi.neuron wrapper objects. Building
        # those would import the entire element class registry (every DAQ reader),
        # which spike sorting does not need; the created documents are returned
        # instead.
        ndi_element_timeseries.addMultiple(
            self._session,
            ndi_timeseries_obj,
            specs,
            element_class="ndi.neuron",
            build_objects=False,
        )
        return neuron_docs

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
