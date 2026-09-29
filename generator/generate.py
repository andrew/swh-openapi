"""Emit an OpenAPI description of the Software Heritage Web API."""

import argparse
import collections
import datetime
import json
import re
import sys
from importlib.metadata import version

import yaml

from collect import collect
from openapi import (
    clean,
    examples_for,
    field_schema,
    nest,
    parse_path,
    summarise,
    TYPES,
)

# Response bodies are described one flat level deep by the upstream docstrings,
# so an operation's 200 is an object of scalars, or an array of them.
CONTENT_TYPES = ["application/json", "application/yaml"]


class Dumper(yaml.SafeDumper):
    """Repeat shared schema objects rather than emitting YAML anchors."""

    def ignore_aliases(self, data):
        return True


def operation(record, unknown):
    doc = record["doc_data"]
    path, path_params = parse_path(record["url_pattern"])
    examples = examples_for(record["url_pattern"], doc.get("examples") or [])

    parameters = []
    documented_args = {a["name"]: a for a in doc.get("args") or []}
    for name, param in path_params.items():
        arg = documented_args.get(name, {})
        entry = {
            "name": name,
            "in": "path",
            "required": True,
            "schema": param["schema"],
        }
        if arg.get("doc"):
            entry["description"] = clean(arg["doc"])
        if name in examples:
            entry["example"] = examples[name]
        parameters.append(entry)

    serializer = record["serializer"]
    if serializer is not None:
        for name, field in serializer().fields.items():
            entry = {
                "name": name,
                "in": "query",
                "required": field.required,
                "schema": field_schema(field),
            }
            if field.help_text:
                entry["description"] = clean(str(field.help_text))
            if name in examples:
                entry["example"] = examples[name]
            parameters.append(entry)
    else:
        for param in doc.get("params") or []:
            schema = TYPES.get(param.get("type"))
            if schema is None:
                unknown.append((param.get("name"), param.get("type")))
                schema = {"type": "string"}
            entry = {
                "name": param["name"],
                "in": "query",
                "required": False,
                "schema": dict(schema),
            }
            if param.get("doc"):
                entry["description"] = clean(param["doc"])
            if param["name"] in examples:
                entry["example"] = examples[param["name"]]
            parameters.append(entry)

    for header in doc.get("reqheaders") or []:
        parameters.append(
            {
                "name": header["name"],
                "in": "header",
                "required": False,
                "schema": {"type": "string"},
                "description": clean(header.get("doc", "")),
            }
        )

    body = nest(doc.get("returns") or [], unknown)
    if body and doc.get("return_type") == "array":
        body = {"type": "array", "items": body}

    responses = {}
    for status in doc.get("status_codes") or []:
        code = str(status["code"]).split()[0]
        responses[code] = {"description": clean(status.get("doc", "")) or code}
    responses.setdefault("200", {"description": "no error"})
    if body:
        responses["200"]["content"] = {ct: {"schema": body} for ct in CONTENT_TYPES}

    headers = {
        h["name"]: {"schema": {"type": "string"}, "description": clean(h.get("doc", ""))}
        for h in doc.get("resheaders") or []
    }
    if headers:
        responses["200"]["headers"] = headers

    op = {
        "operationId": record["view_name"],
        "summary": summarise(doc.get("description", "")),
        "description": clean(doc.get("description", "")),
        "tags": [record["category"]],
        "parameters": parameters,
        "responses": responses,
        # The route as swh-web's own endpoint index names it. Several URL
        # patterns can share one, and the drift check compares against it.
        "x-swh-doc-route": "/api/%s%s" % (record["api_version"], record["route"]),
    }
    if "deprecated" in record["tags"]:
        op["deprecated"] = True

    request = nest(doc.get("inputs") or [], unknown)
    if request:
        if doc.get("input_type") == "array":
            request = {"type": "array", "items": request}
        op["requestBody"] = {
            "content": {ct: {"schema": request} for ct in CONTENT_TYPES}
        }

    return path, {k: v for k, v in op.items() if v is not None}


def schema_name(path, method):
    """Name a component after the route that first uses it."""
    stem = re.sub(r"^/api/\d+/", "", path)
    stem = re.sub(r"{[^}]*}", "", stem)
    words = [word for word in re.split(r"[/_-]+", stem) if word]
    name = "".join(word[:1].upper() + word[1:] for word in words)
    if method != "get":
        name += method.title()
    return name or "Root"


def hoist_schemas(paths):
    """Move body schemas into components so generated clients name them.

    swh-web documents many endpoints with shared docstring fragments, so the
    same object shape recurs across routes and collapses to one component.
    """
    components = {}
    names = {}

    def register(container, key, path, method):
        schema = container.get(key)
        if not isinstance(schema, dict):
            return
        if schema.get("type") == "array":
            register(schema, "items", path, method)
            return
        if schema.get("type") != "object" or not schema.get("properties"):
            return

        fingerprint = json.dumps(schema, sort_keys=True)
        name = names.get(fingerprint)
        if name is None:
            name = schema_name(path, method)
            suffix = 2
            while name in components:
                name = f"{schema_name(path, method)}{suffix}"
                suffix += 1
            components[name] = schema
            names[fingerprint] = name
        container[key] = {"$ref": f"#/components/schemas/{name}"}

    for path, item in sorted(paths.items()):
        for method, operation in sorted(item.items()):
            for response in operation.get("responses", {}).values():
                for media in (response.get("content") or {}).values():
                    register(media, "schema", path, method)
            for media in (operation.get("requestBody", {}).get("content") or {}).values():
                register(media, "schema", path, method)

    return dict(sorted(components.items()))


def unique_operation_ids(paths):
    """Disambiguate the view names shared by several paths or methods.

    swh-web reuses one view name across a route's URL variants, so /directory/
    both with and without a trailing path register as api-1-directory.
    """
    seen = collections.Counter(
        op["operationId"] for item in paths.values() for op in item.values()
    )
    used = set()
    for path, item in sorted(paths.items()):
        for method, op in sorted(item.items()):
            if seen[op["operationId"]] == 1:
                used.add(op["operationId"])
                continue
            args = re.findall(r"{(\w+)}", path)
            for candidate in (
                "-".join([op["operationId"], *args]).replace("_", "-"),
                "-".join([op["operationId"], method, *args]).replace("_", "-"),
            ):
                if candidate not in used:
                    break
            used.add(candidate)
            op["operationId"] = candidate


def build(records):
    unknown = []
    paths = collections.defaultdict(dict)
    for record in records:
        if "hidden" in record["tags"]:
            continue
        path, op = operation(record, unknown)
        for method in record["methods"]:
            if method in ("HEAD", "OPTIONS"):
                continue
            paths[path][method.lower()] = dict(op)

    unique_operation_ids(paths)
    schemas = hoist_schemas(paths)

    document = {
        "openapi": "3.1.0",
        "info": {
            "title": "Software Heritage Web API",
            # CalVer: the description is regenerated as upstream moves, and the
            # swh.web release it came from is recorded alongside it.
            "version": datetime.date.today().isoformat().replace("-", "."),
            "x-swh-web-version": version("swh.web"),
            "description": (
                "Unofficial OpenAPI description of the Software Heritage Web API, "
                "generated from swh-web's own endpoint documentation."
            ),
            "license": {"name": "CC0-1.0"},
        },
        "servers": [{"url": "https://archive.softwareheritage.org"}],
        "components": {
            "schemas": schemas,
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": (
                        "OpenID Connect bearer token, obtained by exchanging an "
                        "offline token at the Software Heritage Keycloak realm. "
                        "Raises the rate limit; anonymous access is allowed."
                    ),
                }
            }
        },
        "security": [{"bearerAuth": []}, {}],
        "paths": dict(sorted(paths.items())),
    }
    return document, unknown


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", default="openapi.gen.yaml")
    args = parser.parse_args()

    records, undocumented = collect()
    document, unknown = build(records)

    with open(args.output, "w") as f:
        yaml.dump(
            document, f, Dumper=Dumper, sort_keys=False, width=100, allow_unicode=True
        )

    operations = sum(len(v) for v in document["paths"].values())
    print(
        f"{document['info']['version']} "
        f"from swh.web {document['info']['x-swh-web-version']}",
        file=sys.stderr,
    )
    print(f"{len(document['paths'])} paths, {operations} operations", file=sys.stderr)
    if undocumented:
        print(f"{len(undocumented)} routed endpoints carry no api_doc:", file=sys.stderr)
        for entry in undocumented:
            print(f"  {entry['url_pattern']}", file=sys.stderr)
    if unknown:
        counts = collections.Counter(unknown)
        print(f"{len(counts)} fields with an unmapped type word:", file=sys.stderr)
        for (name, declared), count in counts.most_common():
            print(f"  {name}: {declared!r} x{count}", file=sys.stderr)


if __name__ == "__main__":
    main()
