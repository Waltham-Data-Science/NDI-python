"""
Tests for Phase 10 Batch 4: Cloud Admin (DOI, Crossref).

Tests DOI generation, Crossref XML, and registration flow.
All external calls are mocked.
"""

import re
from unittest.mock import MagicMock, patch
from xml.etree.ElementTree import fromstring

import pytest

from ndi.cloud.config import CloudConfig
from ndi.cloud.client import CloudClient
from ndi.cloud.admin.crossref import (
    CONSTANTS,
    CrossrefConstants,
    convert_to_crossref,
    create_batch_submission,
)
from ndi.cloud.admin.doi import (
    check_submission,
    create_new_doi,
    register_dataset_doi,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    cfg = CloudConfig(api_url='https://api.test.ndi/v1', token='tok', org_id='org-1')
    c = CloudClient(cfg)
    c._session.request = MagicMock()
    return c


@pytest.fixture
def sample_metadata():
    return {
        'name': 'Visual Cortex Recordings',
        'description': 'Recordings from mouse V1',
        'contributors': [
            {'name': 'Alice Smith'},
            {'name': 'Bob Jones'},
        ],
        'cloud_dataset_id': 'ds-abc-123',
    }


def _ok(data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.content = b'data'
    resp.json.return_value = data
    resp.text = str(data)
    return resp


# ===========================================================================
# CrossrefConstants
# ===========================================================================


class TestCrossrefConstants:
    def test_doi_prefix(self):
        assert CONSTANTS.DOI_PREFIX == '10.63884'

    def test_database_doi(self):
        assert CONSTANTS.DATABASE_DOI == '10.63884/ndic.00000'

    def test_database_url(self):
        assert CONSTANTS.DATABASE_URL == 'https://ndi-cloud.com'

    def test_dataset_base_url(self):
        assert 'ndi-cloud.com/datasets/' in CONSTANTS.DATASET_BASE_URL

    def test_deposit_urls(self):
        assert 'crossref.org' in CONSTANTS.DEPOSIT_URL
        assert 'test.crossref.org' in CONSTANTS.TEST_DEPOSIT_URL

    def test_frozen(self):
        with pytest.raises(AttributeError):
            CONSTANTS.DOI_PREFIX = 'changed'


# ===========================================================================
# DOI generation
# ===========================================================================


class TestDOI:
    def test_create_new_doi_format(self):
        doi = create_new_doi()
        assert doi.startswith('10.63884/ndic.')
        assert len(doi.split('.')[-1]) == 8  # 8 hex chars

    def test_create_new_doi_uniqueness(self):
        dois = {create_new_doi() for _ in range(50)}
        assert len(dois) == 50

    def test_create_new_doi_custom_prefix(self):
        doi = create_new_doi(prefix='10.99999')
        assert doi.startswith('10.99999/ndic.')

    def test_doi_matches_pattern(self):
        doi = create_new_doi()
        assert re.match(r'10\.\d+/ndic\.[0-9a-f]{8}', doi)


# ===========================================================================
# Crossref XML generation
# ===========================================================================


class TestCrossrefXML:
    def test_create_batch_submission_valid_xml(self, sample_metadata):
        doi = '10.63884/ndic.test1234'
        xml = create_batch_submission(sample_metadata, doi)
        assert '<?xml' in xml
        root = fromstring(xml)
        assert 'doi_batch' in root.tag

    def test_xml_contains_doi(self, sample_metadata):
        doi = '10.63884/ndic.abcd1234'
        xml = create_batch_submission(sample_metadata, doi)
        assert doi in xml

    def test_xml_contains_title(self, sample_metadata):
        xml = create_batch_submission(sample_metadata, '10.63884/ndic.test1234')
        assert 'Visual Cortex Recordings' in xml

    def test_xml_contains_contributors(self, sample_metadata):
        xml = create_batch_submission(sample_metadata, '10.63884/ndic.test1234')
        assert 'Alice' in xml
        assert 'Smith' in xml
        assert 'Bob' in xml
        assert 'Jones' in xml

    def test_xml_contains_resource_url(self, sample_metadata):
        xml = create_batch_submission(sample_metadata, '10.63884/ndic.test1234')
        assert 'ds-abc-123' in xml

    def test_xml_contains_database_title(self, sample_metadata):
        xml = create_batch_submission(sample_metadata, '10.63884/ndic.test1234')
        assert CONSTANTS.DATABASE_TITLE in xml


class TestConvertToCrossref:
    def test_basic_conversion(self, sample_metadata):
        result = convert_to_crossref(sample_metadata)
        assert result['title'] == 'Visual Cortex Recordings'
        assert result['description'] == 'Recordings from mouse V1'
        assert len(result['contributors']) == 2
        assert result['doi_prefix'] == '10.63884'

    def test_contributor_name_split(self, sample_metadata):
        result = convert_to_crossref(sample_metadata)
        assert result['contributors'][0]['given_name'] == 'Alice'
        assert result['contributors'][0]['surname'] == 'Smith'

    def test_resource_url(self, sample_metadata):
        result = convert_to_crossref(sample_metadata)
        assert 'ds-abc-123' in result['resource_url']


# ===========================================================================
# Registration flow
# ===========================================================================


class TestRegistration:
    def test_register_no_credentials(self, client, monkeypatch):
        """Without Crossref credentials, registration should skip."""
        monkeypatch.delenv('CROSSREF_USERNAME', raising=False)
        monkeypatch.delenv('CROSSREF_PASSWORD', raising=False)

        # Mock dataset fetch
        client._session.request.return_value = _ok({
            'name': 'Test Dataset',
            'description': 'Test',
            'contributors': [],
        })

        result = register_dataset_doi(client, 'ds-1')
        assert result['submission_status'] == 'skipped'
        assert result['doi'].startswith('10.63884/')
        assert '<?xml' in result['xml']

    def test_check_submission_no_credentials(self, monkeypatch):
        monkeypatch.delenv('CROSSREF_USERNAME', raising=False)
        monkeypatch.delenv('CROSSREF_PASSWORD', raising=False)
        result = check_submission('test_batch')
        assert result['status'] == 'skipped'


# ===========================================================================
# Package imports
# ===========================================================================


class TestAdminImports:
    def test_import_admin_from_cloud(self):
        from ndi.cloud.admin import doi, crossref
        assert callable(doi.create_new_doi)
        assert callable(crossref.create_batch_submission)

    def test_import_constants(self):
        from ndi.cloud.admin.crossref import CONSTANTS
        assert CONSTANTS.DOI_PREFIX == '10.63884'
