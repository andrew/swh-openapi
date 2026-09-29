"""Tests for the mapping between swh-web's documentation and OpenAPI."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "generator"))

from openapi import clean, nest, parse_path, summarise  # noqa: E402


def test_plain_path_has_no_parameters():
    path, params = parse_path("api/1/origin/search/")
    assert path == "/api/1/origin/search/"
    assert params == {}


def test_named_group_becomes_a_path_parameter():
    path, params = parse_path("api/1/content/(?P<q>[0-9a-z_:]*[0-9a-f]+)/raw/")
    assert path == "/api/1/content/{q}/raw/"
    assert params["q"]["schema"] == {
        "type": "string",
        "pattern": "[0-9a-z_:]*[0-9a-f]+",
    }


def test_catch_all_pattern_is_not_recorded():
    _, params = parse_path("api/1/origin/search/(?P<url_pattern>.+)/")
    assert params["url_pattern"]["schema"] == {"type": "string"}


def test_two_groups_in_one_segment():
    # A regex cannot find these by itself: the first group's body ends in a
    # paren that is followed by a colon, not by a separator.
    path, params = parse_path("api/1/extid/(?P<extid_type>.+?):(?P<extid>.+)/")
    assert path == "/api/1/extid/{extid_type}:{extid}/"
    assert sorted(params) == ["extid", "extid_type"]


def test_nested_group_inside_a_parameter():
    path, params = parse_path("api/1/content/known/(?P<q>(?!search).+)/")
    assert path == "/api/1/content/known/{q}/"
    assert params["q"]["schema"]["pattern"] == "(?!search).+"


def test_django_path_converter():
    path, params = parse_path("api/1/origin/save/bulk/request/<uuid:request_id>/")
    assert path == "/api/1/origin/save/bulk/request/{request_id}/"
    assert params["request_id"]["schema"] == {"type": "string", "format": "uuid"}


def test_nest_maps_declared_types():
    unknown = []
    schema = nest(
        [
            {"name": "url", "type": "string", "doc": "the origin url"},
            {"name": "nb_visits", "type": "number", "doc": ""},
            {"name": "has_visits", "type": "boolean", "doc": ""},
        ],
        unknown,
    )
    assert unknown == []
    assert schema["properties"]["url"]["type"] == "string"
    # Every field upstream declares "number" is a count or an identifier.
    assert schema["properties"]["nb_visits"]["type"] == "integer"
    assert schema["properties"]["has_visits"]["type"] == "boolean"


def test_nest_builds_objects_from_dotted_names():
    schema = nest([{"name": "vulnerability.ids", "type": "array", "doc": ""}], [])
    nested = schema["properties"]["vulnerability"]
    assert nested["type"] == "object"
    assert nested["properties"]["ids"]["type"] == "array"


def test_nest_reports_unknown_types_instead_of_guessing():
    unknown = []
    schema = nest([{"name": "snapshot_id", "type": "sha1", "doc": ""}], unknown)
    assert unknown == [("snapshot_id", "sha1")]
    assert schema["properties"]["snapshot_id"]["type"] == "string"


def test_nest_skips_the_unnamed_array_placeholder():
    assert nest([{"name": "-", "type": "string", "doc": "an array of string"}], []) is None


def test_clean_strips_restructuredtext():
    assert clean("a ``literal`` value") == "a literal value"
    assert clean("see `the docs </api/1/doc/>`_ for more") == "see the docs for more"
    assert clean(".. warning::\n\n\tdo not rely on this") == "do not rely on this"


def test_summarise_takes_the_first_sentence():
    assert summarise("Get a content. It may be large.") == "Get a content"
