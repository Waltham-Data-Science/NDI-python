"""Cross-stack conformance tests for the schema-v2 superclass dual-accessor.

Schema v2 (DID-schema V_delta / V_epsilon) names a document's superclasses
directly with a bare ``{"class_name": ...}`` object, whereas legacy ``did_v1``
documents carry only a ``{"definition": "$NDIDOCUMENTPATH/<name>.json"}`` path.
``ndi.document.ndi_document`` must resolve **both** shapes.

The reference contract is ndi-cloud-node ``api/src/dal/class_lineage.ts``
(``computeClassLineage``): for every superclass entry it takes the
``class_name`` **and** the ``definition``-derived name and *unions* them — it
never short-circuits after ``class_name``. The Python sites
(``doc_superclass`` / ``read_blank_definition`` here, and DID-python's
``doc2sql._get_superclass_str``) must match that union semantics so that a
mixed-shape document yields the identical ancestor set across all three stacks.

The discriminating case is a superclass entry that carries **both** a
``class_name`` and a *differing* ``definition``: a correct (union) accessor
reports both names; a buggy (short-circuit) accessor silently narrows the
lineage to the ``class_name`` alone. ``test_mixed_shape_union_no_shortcircuit``
is that conformance pin.

On today's v1 corpus every one of the 127 bundled superclass entries is
``{definition}`` and none carry ``class_name``, so the ``class_name`` branch is
purely additive — these tests guard that the legacy path is unchanged while the
new branch behaves per contract.
"""

import json

import pytest

from ndi import ndi_document
from ndi.common import ndi_common_PathConstants


def _props(class_name, superclasses):
    """Build a minimal document-properties dict with the given superclasses."""
    return {
        "base": {"id": "id", "datestamp": "", "session_id": ""},
        "document_class": {"class_name": class_name, "superclasses": superclasses},
    }


class TestDocSuperclassDualAccessor:
    """``doc_superclass`` / ``doc_isa`` must read class_name-first, union-style."""

    def test_v2_class_name_only_superclass(self):
        """V_epsilon canonical shape: a bare {class_name} superclass resolves
        directly, with NO on-disk definition file required."""
        # 'made_up_parent' has no bundled .json file; class_name is taken as-is.
        doc = ndi_document(_props("child", [{"class_name": "made_up_parent"}]))
        assert doc.doc_superclass() == ["made_up_parent"]
        assert doc.doc_isa("made_up_parent")
        assert doc.doc_isa("child")
        assert not doc.doc_isa("base")

    def test_v1_definition_only_superclass_unchanged(self):
        """Legacy did_v1 shape (the entire current corpus): the definition path
        is read to recover the name. Regression guard — behavior must not change."""
        doc = ndi_document(_props("element_like", [{"definition": "$NDIDOCUMENTPATH/base.json"}]))
        assert "base" in doc.doc_superclass()
        assert doc.doc_isa("base")

    def test_real_bundled_element_doc_isa_base(self):
        """Real bundled definition built from schema: element isa base via the
        definition fallback over the actual on-disk corpus."""
        doc = ndi_document("element")
        assert doc.doc_class() == "element"
        assert doc.doc_isa("base")  # element -> base via {definition} entry

    def test_mixed_shape_dedup(self):
        """An entry with class_name AND a *matching* definition contributes the
        name exactly once (set de-duplication)."""
        doc = ndi_document(
            _props(
                "child",
                [{"class_name": "base", "definition": "$NDIDOCUMENTPATH/base.json"}],
            )
        )
        assert doc.doc_superclass() == ["base"]
        assert doc.doc_isa("base")

    def test_mixed_shape_union_no_shortcircuit(self):
        """CONFORMANCE PIN: an entry with class_name AND a *differing* definition
        must yield BOTH names (union), never just the class_name. A
        short-circuit accessor would drop 'base' and fail this test."""
        doc = ndi_document(
            _props(
                "child",
                # class_name has no file; definition points at the real base.json
                [{"class_name": "custom_marker", "definition": "$NDIDOCUMENTPATH/base.json"}],
            )
        )
        assert set(doc.doc_superclass()) == {"custom_marker", "base"}
        assert doc.doc_isa("custom_marker")
        assert doc.doc_isa("base")

    def test_multiple_superclasses_mixed_shapes(self):
        """A document may mix v2 and legacy superclass entries in one list."""
        doc = ndi_document(
            _props(
                "child",
                [
                    {"class_name": "v2_parent"},
                    {"definition": "$NDIDOCUMENTPATH/base.json"},
                ],
            )
        )
        assert set(doc.doc_superclass()) == {"v2_parent", "base"}
        assert doc.doc_isa("v2_parent")
        assert doc.doc_isa("base")

    def test_single_dict_superclass_class_name(self):
        """MATLAB jsonencode may store a single superclass as a bare dict; it is
        normalized to a list and the class_name is read."""
        doc = ndi_document(_props("child", {"class_name": "lonely_parent"}))
        assert doc.doc_superclass() == ["lonely_parent"]
        assert doc.doc_isa("lonely_parent")

    def test_bare_string_superclass(self):
        """Defensive: an index.json-style bare-string entry is itself the name."""
        doc = ndi_document(_props("child", ["string_parent"]))
        assert "string_parent" in doc.doc_superclass()
        assert doc.doc_isa("string_parent")

    def test_empty_class_name_falls_back_to_definition(self):
        """An empty class_name must not be emitted; the definition still resolves."""
        doc = ndi_document(
            _props(
                "child",
                [{"class_name": "", "definition": "$NDIDOCUMENTPATH/base.json"}],
            )
        )
        assert doc.doc_superclass() == ["base"]

    def test_no_superclasses(self):
        """A root document with empty superclasses resolves to no superclasses."""
        doc = ndi_document(_props("base", []))
        assert doc.doc_superclass() == []
        assert doc.doc_isa("base")  # its own class
        assert not doc.doc_isa("element")

    def test_v_epsilon_flattened_diamond_lineage(self):
        """V_epsilon's observation tier is the first MULTIPLE-INHERITANCE
        (diamond) hierarchy: ``body_weight_observation`` <- ``scalar_observation``
        AND ``scalar_mass``, both reaching ``base``. A produced V_epsilon document
        carries its FLATTENED ancestor list — exactly as the v1 corpus already
        does (e.g. ``stimulus_response_scalar`` carries ``[base,
        stimulus_response]``). The reader must resolve ``isa()`` for every
        ancestor, reached via either parent path, with the shared ancestor
        de-duplicated."""
        doc = ndi_document(
            _props(
                "body_weight_observation",
                [
                    {"class_name": "scalar_observation"},
                    {"class_name": "scalar_mass"},
                    {"class_name": "base"},
                ],
            )
        )
        sc = doc.doc_superclass()
        assert set(sc) == {"scalar_observation", "scalar_mass", "base"}
        assert len(sc) == len(set(sc))  # shared ancestor 'base' appears once
        for ancestor in ("scalar_observation", "scalar_mass", "base"):
            assert doc.doc_isa(ancestor)
        assert doc.doc_isa("body_weight_observation")  # its own leaf class
        assert not doc.doc_isa("subject")  # unrelated branch


@pytest.fixture
def isolated_schema_dir(tmp_path):
    """Point DOCUMENT_PATH at a synthetic schema dir with class-name-shaped
    superclasses, with full isolation of the path + the definition cache.

    Writes a small inheritance chain so we can exercise field inheritance via
    BOTH the v2 ``class_name`` path and the legacy ``definition`` path, which is
    impossible against the bundled corpus (it carries only ``definition``).
    """
    # parent declares a field block that descendants should inherit
    (tmp_path / "parent.json").write_text(
        json.dumps(
            {
                "document_class": {"class_name": "parent", "superclasses": []},
                "parent_block": {"foo": "bar"},
            }
        )
    )
    # v2 child: superclass named by class_name only (no definition path)
    (tmp_path / "child_v2.json").write_text(
        json.dumps(
            {
                "document_class": {
                    "class_name": "child_v2",
                    "superclasses": [{"class_name": "parent"}],
                },
                "child_block": {"x": 1},
            }
        )
    )
    # legacy child: superclass named by definition path only
    (tmp_path / "child_v1.json").write_text(
        json.dumps(
            {
                "document_class": {
                    "class_name": "child_v1",
                    "superclasses": [{"definition": "$NDIDOCUMENTPATH/parent.json"}],
                },
                "child_block": {"x": 1},
            }
        )
    )
    # child whose class_name superclass has NO file on disk (remote v2 corpus)
    (tmp_path / "child_orphan.json").write_text(
        json.dumps(
            {
                "document_class": {
                    "class_name": "child_orphan",
                    "superclasses": [{"class_name": "absent_parent"}],
                },
                "child_block": {"x": 1},
            }
        )
    )

    # V_epsilon observation-tier DIAMOND: body_weight_observation inherits from
    # TWO parents (scalar_observation, scalar_mass) that share a common ancestor
    # (obs_base). read_blank_definition must inherit fields from BOTH branches and
    # visit the shared ancestor exactly once (memoized) — no loop, no duplication.
    (tmp_path / "obs_base.json").write_text(
        json.dumps(
            {
                "document_class": {"class_name": "obs_base", "superclasses": []},
                "obs_base_block": {"shared": True},
            }
        )
    )
    (tmp_path / "scalar_observation.json").write_text(
        json.dumps(
            {
                "document_class": {
                    "class_name": "scalar_observation",
                    "superclasses": [{"class_name": "obs_base"}],
                },
                "observation_block": {"value": None},
            }
        )
    )
    (tmp_path / "scalar_mass.json").write_text(
        json.dumps(
            {
                "document_class": {
                    "class_name": "scalar_mass",
                    "superclasses": [{"class_name": "obs_base"}],
                },
                "mass_block": {"unit": "kg"},
            }
        )
    )
    (tmp_path / "body_weight_observation.json").write_text(
        json.dumps(
            {
                "document_class": {
                    "class_name": "body_weight_observation",
                    "superclasses": [
                        {"class_name": "scalar_observation"},
                        {"class_name": "scalar_mass"},
                    ],
                },
                "leaf_block": {"y": 2},
            }
        )
    )

    original_path = ndi_common_PathConstants._document_path
    original_cache = dict(ndi_document._DEFINITION_CACHE)
    ndi_common_PathConstants.set_paths(document_path=tmp_path)
    ndi_document._DEFINITION_CACHE.clear()
    try:
        yield tmp_path
    finally:
        ndi_common_PathConstants._document_path = original_path
        ndi_document._DEFINITION_CACHE.clear()
        ndi_document._DEFINITION_CACHE.update(original_cache)


class TestReadBlankDefinitionDualAccessor:
    """``read_blank_definition`` must inherit fields through BOTH superclass shapes."""

    def test_v2_class_name_field_inheritance(self, isolated_schema_dir):
        """The v2 class_name path locates parent.json by its class_name and
        inherits its fields (restores inheritance that the definition-only code
        could not do for class_name-shaped superclasses)."""
        definition = ndi_document.read_blank_definition("child_v2")
        assert definition["parent_block"] == {"foo": "bar"}

    def test_v1_definition_field_inheritance_unchanged(self, isolated_schema_dir):
        """The legacy definition path still inherits fields. Regression guard."""
        definition = ndi_document.read_blank_definition("child_v1")
        assert definition["parent_block"] == {"foo": "bar"}

    def test_v2_class_name_missing_file_graceful(self, isolated_schema_dir):
        """A class_name superclass with no on-disk file degrades gracefully:
        no crash, no inherited fields."""
        definition = ndi_document.read_blank_definition("child_orphan")
        assert "parent_block" not in definition
        assert definition["child_block"] == {"x": 1}

    def test_v_epsilon_diamond_multiple_inheritance_flatten(self, isolated_schema_dir):
        """V_epsilon observation-tier DIAMOND: ``body_weight_observation``
        inherits from ``scalar_observation`` AND ``scalar_mass``, which share the
        common ancestor ``obs_base``. The recursive flatten must pull fields from
        BOTH parents and from the shared ancestor — reached via two paths but
        merged exactly once (the ``_DEFINITION_CACHE`` memoization makes the
        diamond loop-free). v1 already exercised multi-ancestor inheritance
        (e.g. ``hartley_calc`` has 6 ancestors); this pins it for the new
        observation tier."""
        definition = ndi_document.read_blank_definition("body_weight_observation")
        # fields inherited from BOTH parent branches...
        assert definition["observation_block"] == {"value": None}
        assert definition["mass_block"] == {"unit": "kg"}
        # ...and from the shared ancestor, present once (no loop / no clobber)...
        assert definition["obs_base_block"] == {"shared": True}
        # ...with the leaf's own field preserved.
        assert definition["leaf_block"] == {"y": 2}
