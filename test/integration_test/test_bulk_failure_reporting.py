"""Rejected indexing operations must fail the local upload command."""

import pytest

from database import bulk_upload


@pytest.mark.parametrize("errors", [1, [{"index": {"status": 400, "error": "invalid document"}}]])
def test_rejected_bulk_documents_raise(errors, fake_elasticsearch_modules, monkeypatch):
    from elasticsearch import helpers

    monkeypatch.setattr(bulk_upload, "get_es", lambda: object())
    monkeypatch.setitem(bulk_upload.TARGETS, "posts_raw", lambda: iter(()))
    monkeypatch.setattr(helpers, "bulk", lambda *args, **kwargs: (0, errors))
    with pytest.raises(RuntimeError, match="Elasticsearch rejected 1 documents"):
        bulk_upload.upload("posts_raw", batch=10, dry_run=False)


def test_successful_bulk_does_not_raise(fake_elasticsearch_modules, monkeypatch):
    from elasticsearch import helpers

    monkeypatch.setattr(bulk_upload, "get_es", lambda: object())
    monkeypatch.setitem(bulk_upload.TARGETS, "posts_raw", lambda: iter(()))
    monkeypatch.setattr(helpers, "bulk", lambda *args, **kwargs: (3, []))
    bulk_upload.upload("posts_raw", batch=10, dry_run=False)
