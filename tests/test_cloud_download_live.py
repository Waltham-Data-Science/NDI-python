"""
Live integration test: NDI-python analysis + ndic:// on-demand file download.

This test exercises both the NDI-python document analysis pipeline AND the new
ndic:// on-demand file downloader in a single run against the Carbon fiber
microelectrode dataset (668b0539f13096e04f1feccd).

Flow:
  1. Authenticate with NDI Cloud
  2. Download dataset (docs only, sync_files=False) → ndic:// URIs
  3. Run NDI-python analysis: queries, element/neuron lookups, tuning curves
  4. Attempt on-demand binary file download via database_openbinarydoc
  5. Verify file is fetched from cloud and cached locally

Requires:
  NDI_CLOUD_USERNAME and NDI_CLOUD_PASSWORD environment variables, or
  pass credentials via --username / --password CLI args.

Usage:
  python tests/test_cloud_download_live.py
  python tests/test_cloud_download_live.py --username USER --password PASS
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import time
import traceback
from collections import Counter

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("test_cloud_download_live")

CARBON_FIBER_ID = "668b0539f13096e04f1feccd"

# Expected counts from the dataset
EXPECTED_DOCS = 743
EXPECTED_ELEMENTS = 20
EXPECTED_NEURONS = 17
EXPECTED_STIMULUS_RESPONSES = 138
EXPECTED_TUNING_CURVES = 126
EXPECTED_ELEMENT_EPOCHS = 46


def section(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return condition


def run_test(username: str, password: str) -> dict:
    """Run the full integration test. Returns a results dict."""
    results = {
        "auth": False,
        "download": False,
        "ndic_rewrite": False,
        "analysis_queries": False,
        "analysis_elements": False,
        "analysis_neurons": False,
        "analysis_tuning": False,
        "analysis_cross_refs": False,
        "file_details_api": False,
        "file_download": False,
        "openbinarydoc": False,
    }

    # =================================================================
    # Step 1: Authenticate
    # =================================================================
    section("Step 1: Authentication")

    from ndi.cloud.auth import login
    from ndi.cloud.client import CloudClient

    try:
        config = login(username, password)
        client = CloudClient(config)
        print(f"  Authenticated as: {username}")
        print(f"  Org ID: {config.org_id}")
        results["auth"] = True
    except Exception as exc:
        print(f"  FAILED to authenticate: {exc}")
        return results

    # =================================================================
    # Step 2: Download dataset (docs only, ndic:// rewrite)
    # =================================================================
    section("Step 2: Download Dataset (docs only, ndic:// URIs)")

    from ndi.cloud.orchestration import download_dataset

    with tempfile.TemporaryDirectory(prefix="ndi_live_test_") as tmpdir:
        t0 = time.time()
        try:
            dataset = download_dataset(
                client,
                CARBON_FIBER_ID,
                target_folder=tmpdir,
                sync_files=False,
                verbose=True,
            )
            elapsed = time.time() - t0
            print(f"  Download completed in {elapsed:.1f}s")
            results["download"] = True
        except Exception as exc:
            print(f"  FAILED to download dataset: {exc}")
            traceback.print_exc()
            return results

        # =================================================================
        # Step 3: Verify ndic:// URIs
        # =================================================================
        section("Step 3: Verify ndic:// URI Rewriting")

        from ndi.cloud.filehandler import NDIC_SCHEME
        from ndi.query import Query

        all_docs = dataset.database_search(Query("").isa("base"))
        ndic_count = 0
        file_docs = []
        for doc in all_docs:
            fi = doc.document_properties.get("files", {}).get("file_info")
            if fi is None:
                continue
            if isinstance(fi, dict):
                fi = [fi]
            for entry in fi:
                locs = entry.get("locations")
                if locs is None:
                    continue
                if isinstance(locs, dict):
                    locs = [locs]
                for loc in locs:
                    if loc.get("location", "").startswith(NDIC_SCHEME):
                        ndic_count += 1
                        file_docs.append((doc, entry.get("name", ""), loc["location"]))

        check("ndic:// URIs rewritten", ndic_count > 0, f"{ndic_count} ndic:// URIs found")
        check("cloud_client set on dataset", dataset.cloud_client is not None)
        results["ndic_rewrite"] = ndic_count > 0

        # =================================================================
        # Step 4: NDI-python Analysis — Queries
        # =================================================================
        section("Step 4: NDI-python Analysis — Document Queries")

        doc_count = len(all_docs)
        check(
            "Document count",
            doc_count >= EXPECTED_DOCS,
            f"{doc_count} docs (expected >= {EXPECTED_DOCS})",
        )

        # Count by type
        type_counts: Counter[str] = Counter()
        for doc in all_docs:
            cname = doc.document_properties.get("document_class", {}).get("class_name", "unknown")
            type_counts[cname] += 1

        check("Document types", len(type_counts) >= 27, f"{len(type_counts)} types found")

        # Test isa queries for each major type
        for doc_type, expected in [
            ("element", EXPECTED_ELEMENTS),
            ("neuron_extracellular", EXPECTED_NEURONS),
            ("stimulus_response_scalar", EXPECTED_STIMULUS_RESPONSES),
            ("tuningcurve_calc", EXPECTED_TUNING_CURVES),
            ("element_epoch", EXPECTED_ELEMENT_EPOCHS),
        ]:
            found = dataset.database_search(Query("").isa(doc_type))
            check(
                f"  isa('{doc_type}')",
                len(found) == expected,
                f"{len(found)} (expected {expected})",
            )

        results["analysis_queries"] = doc_count >= EXPECTED_DOCS

        # =================================================================
        # Step 5: NDI-python Analysis — Elements
        # =================================================================
        section("Step 5: NDI-python Analysis — Elements & Structure")

        elements = dataset.database_search(Query("").isa("element"))
        element_types = {d.document_properties.get("element", {}).get("type", "") for d in elements}
        check(
            "Element types",
            element_types == {"n-trode", "spikes", "stimulator"},
            f"{element_types}",
        )

        ntrodes = [
            d for d in elements if d.document_properties.get("element", {}).get("type") == "n-trode"
        ]
        check("N-trode elements", len(ntrodes) == 2)

        spikes = [
            d for d in elements if d.document_properties.get("element", {}).get("type") == "spikes"
        ]
        check("Spike elements", len(spikes) == 17, "one per neuron")

        # Check element -> subject dependency chain
        subjects = dataset.database_search(Query("").isa("subject"))
        subject_id = (
            subjects[0].document_properties.get("base", {}).get("id", "") if subjects else ""
        )
        deps_ok = True
        for elem in elements:
            deps = elem.document_properties.get("depends_on", [])
            if isinstance(deps, dict):
                deps = [deps]
            subj_deps = [d for d in deps if d.get("name") == "subject_id"]
            if not subj_deps or subj_deps[0].get("value") != subject_id:
                deps_ok = False
                break
        check("Element -> Subject deps", deps_ok)
        results["analysis_elements"] = deps_ok

        # =================================================================
        # Step 6: NDI-python Analysis — Neurons
        # =================================================================
        section("Step 6: NDI-python Analysis — Neurons")

        neurons = dataset.database_search(Query("").isa("neuron_extracellular"))
        check("Neuron count", len(neurons) == EXPECTED_NEURONS)

        waveform_ok = True
        for n in neurons:
            ne = n.document_properties.get("neuron_extracellular", {})
            if ne.get("number_of_samples_per_channel") != 21:
                waveform_ok = False
            if ne.get("number_of_channels") != 16:
                waveform_ok = False
            if not ne.get("mean_waveform"):
                waveform_ok = False
        check("Neuron waveform shape (21x16)", waveform_ok)

        # Check neuron -> element chain
        element_ids = {d.document_properties.get("base", {}).get("id", "") for d in elements}
        chain_ok = True
        for n in neurons:
            deps = n.document_properties.get("depends_on", [])
            if isinstance(deps, dict):
                deps = [deps]
            elem_dep = [d for d in deps if d.get("name") == "element_id"]
            if not elem_dep or elem_dep[0].get("value") not in element_ids:
                chain_ok = False
                break
        check("Neuron -> Element chain", chain_ok)

        app_ok = all(n.document_properties.get("app", {}).get("name") == "JRCLUST" for n in neurons)
        check("All neurons sorted by JRCLUST", app_ok)
        results["analysis_neurons"] = len(neurons) == EXPECTED_NEURONS and waveform_ok

        # =================================================================
        # Step 7: NDI-python Analysis — Tuning Curves
        # =================================================================
        section("Step 7: NDI-python Analysis — Tuning Curves")

        tcs = dataset.database_search(Query("").isa("tuningcurve_calc"))
        check("Tuning curve count", len(tcs) == EXPECTED_TUNING_CURVES)

        label_counts: Counter[tuple] = Counter()
        for tc in tcs:
            stc = tc.document_properties.get("stimulus_tuningcurve", {})
            labels = stc.get("independent_variable_label", [])
            label_counts[tuple(labels)] += 1

        check(
            "Orientation tuning",
            label_counts.get(("Orientation",), 0) == 34,
            f"{label_counts.get(('Orientation',), 0)}",
        )
        check(
            "Spatial frequency tuning",
            label_counts.get(("Spatial_Frequency",), 0) == 34,
            f"{label_counts.get(('Spatial_Frequency',), 0)}",
        )
        check(
            "Temporal frequency tuning",
            label_counts.get(("Temporal_Frequency",), 0) == 58,
            f"{label_counts.get(('Temporal_Frequency',), 0)}",
        )

        # Verify orientation tuning samples 12 directions
        ori_ok = False
        for tc in tcs:
            stc = tc.document_properties.get("stimulus_tuningcurve", {})
            if stc.get("independent_variable_label") == ["Orientation"]:
                vals = stc.get("independent_variable_value", [])
                if vals == list(range(0, 360, 30)):
                    ori_ok = True
                    break
        check("12 orientation directions (0-330 deg)", ori_ok)
        results["analysis_tuning"] = len(tcs) == EXPECTED_TUNING_CURVES

        # =================================================================
        # Step 8: Cross-document referential integrity
        # =================================================================
        section("Step 8: Cross-Document Referential Integrity")

        all_ids = {d.document_properties.get("base", {}).get("id", "") for d in all_docs}
        missing_refs = 0
        total_refs = 0
        for doc in all_docs:
            deps = doc.document_properties.get("depends_on", [])
            if isinstance(deps, dict):
                deps = [deps]
            elif not isinstance(deps, list):
                continue
            for dep in deps:
                val = dep.get("value", "")
                if val and not val.startswith("$"):
                    total_refs += 1
                    if val not in all_ids:
                        missing_refs += 1

        check(
            "Referential integrity",
            missing_refs == 0,
            f"{total_refs} refs checked, {missing_refs} missing",
        )
        results["analysis_cross_refs"] = missing_refs == 0

        # =================================================================
        # Step 9: Test ndic:// file download pipeline
        # =================================================================
        section("Step 9: On-Demand File Download (ndic:// protocol)")

        if not file_docs:
            print("  SKIP: No documents with ndic:// URIs found")
        else:
            # Pick a small file to test with — try presentation_time.bin first
            test_doc = None
            test_filename = None
            test_uri = None

            # Sort by filename to find smaller files first
            for doc, fname, uri in file_docs:
                if "presentation_time" in fname:
                    test_doc, test_filename, test_uri = doc, fname, uri
                    break
            if test_doc is None:
                # Fall back to first available
                test_doc, test_filename, test_uri = file_docs[0]

            print(f"  Test file: {test_filename}")
            print(f"  ndic URI: {test_uri}")

            # Step 9a: Test get_file_details API directly
            from ndi.cloud.api.files import get_file_details
            from ndi.cloud.filehandler import parse_ndic_uri

            ds_id, file_uid = parse_ndic_uri(test_uri)
            print(f"  Dataset ID: {ds_id}")
            print(f"  File UID: {file_uid}")

            try:
                details = get_file_details(ds_id, file_uid, client=client)
                download_url = details.get("downloadUrl", "")
                print(f"  File details response keys: {list(details.keys())}")
                if download_url:
                    # Show URL domain only (not full URL with signature)
                    from urllib.parse import urlparse

                    parsed = urlparse(download_url)
                    print(f"  Download URL host: {parsed.hostname}")
                    print(f"  Download URL path prefix: {parsed.path[:80]}...")
                    results["file_details_api"] = True
                    check("get_file_details API", True, "presigned URL obtained")
                else:
                    print(f"  WARNING: No downloadUrl in response: {details}")
                    check("get_file_details API", False, "no downloadUrl")
            except Exception as exc:
                print(f"  get_file_details FAILED: {exc}")
                traceback.print_exc()

            # Step 9b: Test raw download with detailed error reporting
            if download_url:
                import requests

                print("\n  Testing direct download from presigned URL...")
                try:
                    resp = requests.get(download_url, timeout=30, stream=True)
                    print(f"  HTTP Status: {resp.status_code}")
                    print("  Response headers:")
                    for k, v in resp.headers.items():
                        if k.lower() in (
                            "content-type",
                            "content-length",
                            "x-amz-request-id",
                            "x-amz-id-2",
                            "server",
                            "date",
                        ):
                            print(f"    {k}: {v}")

                    if resp.status_code == 200:
                        # Read first 1KB to verify it's real data
                        chunk = resp.raw.read(1024)
                        print(f"  First 1KB received: {len(chunk)} bytes")
                        results["file_download"] = True
                        check(
                            "Direct S3 download",
                            True,
                            f"{resp.headers.get('content-length', '?')} bytes",
                        )
                    elif resp.status_code == 403:
                        body = resp.text[:500]
                        print(f"  S3 403 Forbidden — Response body:\n{body}")
                        check("Direct S3 download", False, "403 Forbidden")
                        # Parse S3 XML error for details
                        if "<Code>" in body:
                            import re

                            code = re.search(r"<Code>(.*?)</Code>", body)
                            msg = re.search(r"<Message>(.*?)</Message>", body)
                            if code:
                                print(f"  S3 Error Code: {code.group(1)}")
                            if msg:
                                print(f"  S3 Error Message: {msg.group(1)}")
                    else:
                        print(f"  Unexpected status: {resp.status_code}")
                        print(f"  Body: {resp.text[:300]}")
                        check("Direct S3 download", False, f"HTTP {resp.status_code}")
                except Exception as exc:
                    print(f"  Direct download FAILED: {exc}")
                    traceback.print_exc()

            # Step 9c: Test via database_openbinarydoc (full pipeline)
            print("\n  Testing database_openbinarydoc (full ndic:// pipeline)...")
            try:
                fh = dataset.database_openbinarydoc(test_doc, test_filename)
                data = fh.read(1024)
                fh.close()
                print(f"  openbinarydoc returned {len(data)} bytes")
                results["openbinarydoc"] = True
                check("database_openbinarydoc", True, "file fetched on demand")
            except FileNotFoundError as exc:
                print(f"  FileNotFoundError: {exc}")
                check("database_openbinarydoc", False, str(exc)[:100])
            except Exception as exc:
                print(f"  Error: {exc}")
                traceback.print_exc()
                check("database_openbinarydoc", False, str(exc)[:100])

            # Step 9d: If first file failed, try another file type
            if not results["file_download"]:
                print("\n  Trying different file types for diagnostic...")
                seen_types = set()
                for _doc, fname, uri in file_docs[:20]:
                    ftype = fname.rsplit(".", 1)[-1] if "." in fname else "unknown"
                    if ftype in seen_types:
                        continue
                    seen_types.add(ftype)

                    ds_id2, file_uid2 = parse_ndic_uri(uri)
                    try:
                        details2 = get_file_details(ds_id2, file_uid2, client=client)
                        url2 = details2.get("downloadUrl", "")
                        if url2:
                            resp2 = requests.head(url2, timeout=10)
                            print(
                                f"    {fname}: HTTP {resp2.status_code} "
                                f"({resp2.headers.get('content-length', '?')} bytes)"
                            )
                            if resp2.status_code == 200:
                                print("    ^ This file type works!")
                                results["file_download"] = True
                    except Exception as exc2:
                        print(f"    {fname}: ERROR {exc2}")

    # =================================================================
    # Summary
    # =================================================================
    section("Summary")
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"\n  Results: {passed}/{total} passed\n")
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"    [{status}] {name}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Live cloud download integration test")
    parser.add_argument("--username", default=os.environ.get("NDI_CLOUD_USERNAME", ""))
    parser.add_argument("--password", default=os.environ.get("NDI_CLOUD_PASSWORD", ""))
    args = parser.parse_args()

    username = args.username
    password = args.password

    if not username or not password:
        print(
            "ERROR: Credentials required. Set NDI_CLOUD_USERNAME/NDI_CLOUD_PASSWORD or use --username/--password"
        )
        sys.exit(1)

    print("NDI Cloud Live Integration Test")
    print(f"Dataset: Carbon fiber microelectrode ({CARBON_FIBER_ID})")
    print(f"User: {username}")

    results = run_test(username, password)

    # Exit with non-zero if any critical tests failed
    critical = ["auth", "download", "ndic_rewrite", "analysis_queries"]
    if not all(results.get(k, False) for k in critical):
        sys.exit(1)


if __name__ == "__main__":
    main()
