"""
ndi.cloud.admin.crossref - Crossref metadata and XML generation.

Constants and helpers for submitting dataset DOIs to Crossref.

MATLAB equivalent: +ndi/+cloud/+admin/+crossref/Constants.m,
    createBatchSubmission.m
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring


@dataclass(frozen=True)
class CrossrefConstants:
    """Constants for Crossref DOI registration."""

    DOI_PREFIX: str = "10.63884"
    DATABASE_DOI: str = "10.63884/ndic.00000"
    DATABASE_URL: str = "https://ndi-cloud.com"
    DATABASE_TITLE: str = "NDI Cloud Open Datasets"
    DATASET_BASE_URL: str = "https://www.ndi-cloud.com/datasets/"
    DEPOSIT_URL: str = "https://doi.crossref.org/servlet/deposit"
    TEST_DEPOSIT_URL: str = "https://test.crossref.org/servlet/deposit"


CONSTANTS = CrossrefConstants()


def create_batch_submission(
    dataset_metadata: dict[str, Any],
    doi: str,
) -> str:
    """Create a Crossref batch deposit XML string for a dataset.

    Args:
        dataset_metadata: Dict with keys ``name``, ``description``,
            ``contributors`` (list of dicts with ``name``), and
            ``cloud_dataset_id``.
        doi: The DOI to register (e.g. ``10.63884/ndic.00001``).

    Returns:
        XML string suitable for Crossref deposit.
    """
    root = Element("doi_batch")
    root.set("version", "5.3.1")
    root.set("xmlns", "http://www.crossref.org/schema/5.3.1")

    # Head
    head = SubElement(root, "head")
    doi_batch_id = SubElement(head, "doi_batch_id")
    doi_batch_id.text = doi.replace("/", "_")
    timestamp = SubElement(head, "timestamp")
    from datetime import datetime, timezone

    timestamp.text = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    depositor = SubElement(head, "depositor")
    dep_name = SubElement(depositor, "depositor_name")
    dep_name.text = "NDI Cloud"
    dep_email = SubElement(depositor, "email_address")
    dep_email.text = "ndi-cloud@brandeis.edu"
    registrant = SubElement(head, "registrant")
    registrant.text = "NDI Cloud"

    # Body — database entry
    body = SubElement(root, "body")
    database = SubElement(body, "database")
    db_meta = SubElement(database, "database_metadata")
    titles = SubElement(db_meta, "titles")
    title = SubElement(titles, "title")
    title.text = CONSTANTS.DATABASE_TITLE

    # Dataset entry
    dataset = SubElement(database, "dataset")
    dataset.set("dataset_type", "record")

    # Contributors
    contributors_data = dataset_metadata.get("contributors", [])
    if contributors_data:
        contributors_el = SubElement(dataset, "contributors")
        for i, c in enumerate(contributors_data):
            person = SubElement(contributors_el, "person_name")
            person.set("contributor_role", "author")
            person.set("sequence", "first" if i == 0 else "additional")
            name_parts = c.get("name", "Unknown").split(" ", 1)
            given = SubElement(person, "given_name")
            given.text = name_parts[0]
            surname = SubElement(person, "surname")
            surname.text = name_parts[1] if len(name_parts) > 1 else name_parts[0]

    # Titles
    ds_titles = SubElement(dataset, "titles")
    ds_title = SubElement(ds_titles, "title")
    ds_title.text = dataset_metadata.get("name", "Untitled Dataset")

    # Description
    desc = dataset_metadata.get("description", "")
    if desc:
        description_el = SubElement(dataset, "description")
        description_el.text = desc

    # DOI data
    doi_data = SubElement(dataset, "doi_data")
    doi_el = SubElement(doi_data, "doi")
    doi_el.text = doi
    resource = SubElement(doi_data, "resource")
    cloud_id = dataset_metadata.get("cloud_dataset_id", "")
    resource.text = f"{CONSTANTS.DATASET_BASE_URL}{cloud_id}"

    return tostring(root, encoding="unicode", xml_declaration=True)


def convert_to_crossref(dataset_metadata: dict[str, Any]) -> dict[str, Any]:
    """Convert NDI dataset metadata to Crossref-compatible format.

    Args:
        dataset_metadata: NDI dataset dict.

    Returns:
        Dict in Crossref metadata format.
    """
    return {
        "title": dataset_metadata.get("name", ""),
        "description": dataset_metadata.get("description", ""),
        "contributors": convert_contributors(dataset_metadata),
        "doi_prefix": CONSTANTS.DOI_PREFIX,
        "database_title": CONSTANTS.DATABASE_TITLE,
        "resource_url": (
            f"{CONSTANTS.DATASET_BASE_URL}" f"{dataset_metadata.get('cloud_dataset_id', '')}"
        ),
        "date": convert_dataset_date(dataset_metadata),
        "funding": convert_funding(dataset_metadata),
        "license": convert_license(dataset_metadata),
        "related_publications": convert_related_publications(dataset_metadata),
    }


# ---------------------------------------------------------------------------
# Detailed conversion helpers (MATLAB: +crossref/+conversion/)
# ---------------------------------------------------------------------------


def convert_contributors(
    dataset_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert contributor list to Crossref PersonName format.

    MATLAB equivalent: +crossref/+conversion/convertContributors.m
    """
    result: list[dict[str, Any]] = []
    for i, c in enumerate(dataset_metadata.get("contributors", [])):
        name = c.get("name", c.get("firstName", "") + " " + c.get("lastName", ""))
        name = name.strip() or "Unknown"
        parts = name.split(" ", 1)
        given = parts[0]
        surname = parts[1] if len(parts) > 1 else parts[0]

        entry: dict[str, Any] = {
            "given_name": c.get("firstName", given),
            "surname": c.get("lastName", surname),
            "role": "author",
            "sequence": "first" if i == 0 else "additional",
        }

        # Handle ORCID
        orcid = c.get("orcid", "")
        if orcid:
            if not orcid.startswith("http"):
                orcid = f"https://orcid.org/{orcid}"
            entry["orcid"] = orcid

        result.append(entry)
    return result


def convert_dataset_date(
    dataset_metadata: dict[str, Any],
) -> dict[str, str]:
    """Convert dataset timestamps to Crossref date format.

    MATLAB equivalent: +crossref/+conversion/convertDatasetDate.m
    """
    created = dataset_metadata.get("createdAt", "")
    updated = dataset_metadata.get("updatedAt", "")

    def _parse_date(ts: str) -> dict[str, str]:
        if not ts:
            now = datetime.now(timezone.utc)
            return {"year": str(now.year), "month": f"{now.month:02d}", "day": f"{now.day:02d}"}
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return {"year": str(dt.year), "month": f"{dt.month:02d}", "day": f"{dt.day:02d}"}
        except (ValueError, AttributeError):
            now = datetime.now(timezone.utc)
            return {"year": str(now.year), "month": f"{now.month:02d}", "day": f"{now.day:02d}"}

    return {
        "creation_date": _parse_date(created),
        "update_date": _parse_date(updated),
        "publication_date": _parse_date(created),
    }


def convert_funding(
    dataset_metadata: dict[str, Any],
) -> list[dict[str, str]]:
    """Convert funding information to Crossref FrProgram format.

    MATLAB equivalent: +crossref/+conversion/convertFunding.m
    """
    funding = dataset_metadata.get("funding", [])
    if not funding:
        return []
    return [
        {"funder_name": f.get("source", f.get("name", "Unknown"))}
        for f in funding
        if isinstance(f, dict)
    ]


def convert_license(
    dataset_metadata: dict[str, Any],
) -> dict[str, str]:
    """Convert license information to Crossref AiProgram format.

    MATLAB equivalent: +crossref/+conversion/convertLicense.m
    """
    license_info = dataset_metadata.get("license", "")
    if not license_info:
        return {}

    # Map common license names to URLs
    LICENSE_URLS = {
        "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
        "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
        "CC-BY-NC-4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
        "CC-BY-NC-SA-4.0": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    }

    if isinstance(license_info, dict):
        name = license_info.get("name", "")
        url = license_info.get("url", license_info.get("webpage", ""))
    else:
        name = str(license_info)
        url = ""

    # Normalize name
    normalized = name.replace("ccByNcSa4_0", "CC-BY-NC-SA-4.0")
    if "Attribution 4.0" in normalized:
        normalized = "CC-BY-4.0"

    if not url:
        url = LICENSE_URLS.get(normalized, "")

    return {"name": normalized or name, "url": url} if name else {}


def convert_related_publications(
    dataset_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert associated publications to Crossref RelProgram format.

    MATLAB equivalent: +crossref/+conversion/convertRelatedPublications.m

    Returns a list of related item dicts.  Each dict contains whatever
    fields are available in the source record (e.g. ``title``, ``doi``,
    ``url``).  Returns an empty list when the dataset has no associated
    publications.
    """
    pubs = dataset_metadata.get("associatedPublications", [])
    if not pubs:
        return []
    result: list[dict[str, Any]] = []
    for pub in pubs:
        if not isinstance(pub, dict):
            continue
        item: dict[str, Any] = {}
        if pub.get("title"):
            item["title"] = pub["title"]
        if pub.get("doi"):
            item["doi"] = pub["doi"]
        if pub.get("url"):
            item["url"] = pub["url"]
        if pub.get("citation"):
            item["citation"] = pub["citation"]
        result.append(item)
    return result
