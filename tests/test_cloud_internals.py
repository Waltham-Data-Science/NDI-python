"""
Tests for Phase 11 Batch 11C: Cloud Sync Internals + Admin Converters.

Tests internal helpers, sync validation, and Crossref conversion functions.
"""

from unittest.mock import MagicMock, patch

import pytest

from ndi.cloud.config import CloudConfig
from ndi.cloud.client import CloudClient
from ndi.cloud.internal import (
    list_local_documents,
    get_file_uids_from_documents,
    files_not_yet_uploaded,
    validate_sync,
    dataset_session_id_from_docs,
)
from ndi.cloud.admin.crossref import (
    convert_contributors,
    convert_dataset_date,
    convert_funding,
    convert_license,
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


def _doc(doc_id, session_id='sess-1', file_uid=''):
    d = MagicMock()
    props = {
        'base': {'id': doc_id, 'session_id': session_id},
    }
    if file_uid:
        props['file_uid'] = file_uid
    d.document_properties = props
    return d


# ===========================================================================
# Internal helpers
# ===========================================================================


class TestListLocalDocuments:
    def test_returns_docs_and_ids(self):
        dataset = MagicMock()
        dataset.session.database_search.return_value = [
            _doc('d1'), _doc('d2'),
        ]
        docs, ids = list_local_documents(dataset)
        assert len(docs) == 2
        assert ids == ['d1', 'd2']

    def test_empty_dataset(self):
        dataset = MagicMock()
        dataset.session.database_search.return_value = []
        docs, ids = list_local_documents(dataset)
        assert docs == []
        assert ids == []


class TestGetFileUids:
    def test_from_file_uid(self):
        docs = [_doc('d1', file_uid='f-abc'), _doc('d2')]
        uids = get_file_uids_from_documents(docs)
        assert 'f-abc' in uids

    def test_from_file_info(self):
        d = MagicMock()
        d.document_properties = {
            'base': {'id': 'x'},
            'files': {
                'file_info': [
                    {'locations': [{'uid': 'uid-1'}, {'uid': 'uid-2'}]},
                ],
            },
        }
        uids = get_file_uids_from_documents([d])
        assert 'uid-1' in uids
        assert 'uid-2' in uids

    def test_empty(self):
        assert get_file_uids_from_documents([]) == []

    def test_deduplication(self):
        docs = [_doc('d1', file_uid='same'), _doc('d2', file_uid='same')]
        uids = get_file_uids_from_documents(docs)
        assert uids.count('same') == 1


class TestFilesNotYetUploaded:
    def test_filters_already_uploaded(self, client):
        manifest = [
            {'uid': 'f1', 'docid': 'd1'},
            {'uid': 'f2', 'docid': 'd2'},
        ]
        with patch('ndi.cloud.api.files.list_files') as mock_list:
            mock_list.return_value = [{'uid': 'f1'}]
            result = files_not_yet_uploaded(manifest, client, 'ds-1')
            assert len(result) == 1
            assert result[0]['uid'] == 'f2'

    def test_all_new(self, client):
        manifest = [{'uid': 'f1'}, {'uid': 'f2'}]
        with patch('ndi.cloud.api.files.list_files') as mock_list:
            mock_list.return_value = []
            result = files_not_yet_uploaded(manifest, client, 'ds-1')
            assert len(result) == 2


class TestValidateSync:
    def test_basic_comparison(self, client):
        dataset = MagicMock()
        dataset.session.database_search.return_value = [_doc('d1'), _doc('d2')]

        with patch('ndi.cloud.internal.list_remote_document_ids') as mock_remote:
            mock_remote.return_value = {'d2': 'api-2', 'd3': 'api-3'}
            report = validate_sync(client, dataset, 'ds-1')

        assert 'd1' in report['local_only_ids']
        assert 'd3' in report['remote_only_ids']
        assert 'd2' in report['common_ids']
        assert report['local_count'] == 2
        assert report['remote_count'] == 2


class TestDatasetSessionId:
    def test_single_session(self):
        docs = [_doc('d1', session_id='sess-1'), _doc('d2', session_id='sess-1')]
        assert dataset_session_id_from_docs(docs) == 'sess-1'

    def test_multiple_sessions(self):
        docs = [_doc('d1', session_id='s1'), _doc('d2', session_id='s2')]
        assert dataset_session_id_from_docs(docs) == ''

    def test_empty(self):
        assert dataset_session_id_from_docs([]) == ''


# ===========================================================================
# Crossref converters
# ===========================================================================


class TestConvertContributors:
    def test_basic_conversion(self):
        meta = {
            'contributors': [
                {'name': 'Alice Smith'},
                {'name': 'Bob Jones'},
            ],
        }
        result = convert_contributors(meta)
        assert len(result) == 2
        assert result[0]['given_name'] == 'Alice'
        assert result[0]['surname'] == 'Smith'
        assert result[0]['sequence'] == 'first'
        assert result[1]['sequence'] == 'additional'

    def test_with_first_last_name_fields(self):
        meta = {
            'contributors': [
                {'firstName': 'Jane', 'lastName': 'Doe'},
            ],
        }
        result = convert_contributors(meta)
        assert result[0]['given_name'] == 'Jane'
        assert result[0]['surname'] == 'Doe'

    def test_with_orcid(self):
        meta = {
            'contributors': [
                {'name': 'Test User', 'orcid': '0000-0001-2345-6789'},
            ],
        }
        result = convert_contributors(meta)
        assert result[0]['orcid'] == 'https://orcid.org/0000-0001-2345-6789'

    def test_orcid_already_url(self):
        meta = {
            'contributors': [
                {'name': 'X Y', 'orcid': 'https://orcid.org/0000-0001-2345-6789'},
            ],
        }
        result = convert_contributors(meta)
        assert result[0]['orcid'].startswith('https://orcid.org/')

    def test_empty_contributors(self):
        assert convert_contributors({}) == []


class TestConvertDatasetDate:
    def test_with_timestamps(self):
        meta = {
            'createdAt': '2024-06-15T10:30:00Z',
            'updatedAt': '2024-07-01T12:00:00Z',
        }
        result = convert_dataset_date(meta)
        assert result['creation_date']['year'] == '2024'
        assert result['creation_date']['month'] == '06'
        assert result['creation_date']['day'] == '15'
        assert result['update_date']['month'] == '07'

    def test_without_timestamps(self):
        result = convert_dataset_date({})
        # Should default to current date
        assert 'creation_date' in result
        assert len(result['creation_date']['year']) == 4


class TestConvertFunding:
    def test_with_funding(self):
        meta = {
            'funding': [
                {'source': 'NIH'},
                {'name': 'NSF'},
            ],
        }
        result = convert_funding(meta)
        assert len(result) == 2
        assert result[0]['funder_name'] == 'NIH'
        assert result[1]['funder_name'] == 'NSF'

    def test_no_funding(self):
        assert convert_funding({}) == []


class TestConvertLicense:
    def test_cc_by_4(self):
        meta = {'license': 'CC-BY-4.0'}
        result = convert_license(meta)
        assert result['name'] == 'CC-BY-4.0'
        assert 'creativecommons.org' in result['url']

    def test_dict_license(self):
        meta = {'license': {'name': 'CC0-1.0', 'url': 'https://example.com/cc0'}}
        result = convert_license(meta)
        assert result['name'] == 'CC0-1.0'
        assert result['url'] == 'https://example.com/cc0'

    def test_no_license(self):
        assert convert_license({}) == {}

    def test_matlab_format(self):
        meta = {'license': 'ccByNcSa4_0'}
        result = convert_license(meta)
        assert 'NC-SA' in result['name']


# ===========================================================================
# Sync validate via operations
# ===========================================================================


class TestSyncValidateOps:
    def test_validate_sync_via_operations(self, client):
        from ndi.cloud.sync.operations import validate_sync as ops_validate
        dataset = MagicMock()
        dataset.session.database_search.return_value = [_doc('d1')]
        with patch('ndi.cloud.internal.list_remote_document_ids') as mock_remote:
            mock_remote.return_value = {'d1': 'api-1', 'd2': 'api-2'}
            report = ops_validate(client, dataset, 'ds-1')
        assert 'd2' in report['remote_only_ids']


# ===========================================================================
# Imports
# ===========================================================================


class TestInternalsImports:
    def test_import_internal_helpers(self):
        from ndi.cloud.internal import (
            list_local_documents,
            get_file_uids_from_documents,
            files_not_yet_uploaded,
            validate_sync,
            dataset_session_id_from_docs,
        )
        assert callable(list_local_documents)

    def test_import_crossref_converters(self):
        from ndi.cloud.admin.crossref import (
            convert_contributors,
            convert_dataset_date,
            convert_funding,
            convert_license,
        )
        assert callable(convert_contributors)
