"""Tests for ndi.ido module."""

import re

from ndi import Ido


class TestIdo:
    """Test cases for the Ido class."""

    def test_create_new_id(self):
        """Test that creating an Ido generates a unique ID."""
        ido = Ido()
        assert ido.id is not None
        assert isinstance(ido.id, str)
        assert len(ido.id) > 0

    def test_id_format(self):
        """Test that ID follows expected format (hex_hex)."""
        ido = Ido()
        # ID should be in format: hexstring_hexstring
        assert "_" in ido.id
        parts = ido.id.split("_")
        assert len(parts) == 2
        # Both parts should be valid hex strings
        for part in parts:
            assert re.match(r"^[0-9a-f]+$", part), f"Part '{part}' is not valid hex"

    def test_unique_ids(self):
        """Test that multiple Ido instances have unique IDs."""
        ids = [Ido().id for _ in range(100)]
        assert len(ids) == len(set(ids)), "Generated IDs should be unique"

    def test_create_with_existing_id(self):
        """Test creating Ido with an existing ID."""
        existing_id = "abc123_def456"
        ido = Ido(id=existing_id)
        assert ido.id == existing_id

    def test_str_representation(self):
        """Test string representation returns the ID."""
        ido = Ido()
        assert str(ido) == ido.id

    def test_repr(self):
        """Test repr shows class name and ID."""
        ido = Ido()
        repr_str = repr(ido)
        assert "Ido(" in repr_str
        assert ido.id in repr_str

    def test_id_sortable_by_time(self):
        """Test that IDs are sortable by creation time."""
        import time

        id1 = Ido().id
        time.sleep(0.01)  # Small delay
        id2 = Ido().id
        time.sleep(0.01)
        id3 = Ido().id

        # When sorted alphabetically, they should maintain creation order
        sorted_ids = sorted([id3, id1, id2])
        assert sorted_ids == [id1, id2, id3], "IDs should sort by creation time"
