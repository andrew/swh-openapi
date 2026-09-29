"""Turn collected swh-web endpoint metadata into an OpenAPI document."""

import re
import urllib.parse

# Type words as they appear in swh-web's httpdomain docstrings. They are
# written by hand and inconsistent, so unknown words fall back to string and
# are reported rather than guessed at.
TYPES = {
    "string": {"type": "string"},
    "str": {"type": "string"},
    # Every field declared "number" upstream is a count or an identifier.
    "number": {"type": "integer"},
    "int": {"type": "integer"},
    "boolean": {"type": "boolean"},
    "bool": {"type": "boolean"},
    "array": {"type": "array", "items": {}},
    "object": {"type": "object"},
    "date": {"type": "string", "format": "date-time"},
}

# DRF field class name -> schema. Matched against the class and its bases, so
# swh's own fields resolve through whatever they subclass.
FIELDS = {
    "CharField": {"type": "string"},
    "IntegerField": {"type": "integer"},
    "FloatField": {"type": "number"},
    "BooleanField": {"type": "boolean"},
    "DateTimeField": {"type": "string", "format": "date-time"},
    "ChoiceField": {"type": "string"},
    "ListField": {"type": "array", "items": {}},
    "URLField": {"type": "string", "format": "uri"},
}

NAMED_GROUP = re.compile(r"\(\?P<(?P<name>\w+)>")
PATH_CONV = re.compile(r"<(?:(?P<conv>\w+):)?(?P<name>\w+)>")

CONVERTERS = {
    "int": {"type": "integer"},
    "uuid": {"type": "string", "format": "uuid"},
    "slug": {"type": "string"},
    "path": {"type": "string"},
    "str": {"type": "string"},
}


def parse_path(url_pattern):
    """Convert a Django URL pattern to an OpenAPI path and its parameters.

    Named groups are found by scanning for balanced parentheses rather than by
    regex: a single path segment can hold several of them, and their bodies
    contain groups of their own, as in extid/(?P<extid_type>.+?):(?P<extid>.+)/
    """
    params = {}
    out = []
    pos = 0
    while True:
        match = NAMED_GROUP.search(url_pattern, pos)
        if match is None:
            out.append(url_pattern[pos:])
            break
        out.append(url_pattern[pos : match.start()])

        depth = 1
        index = match.end()
        while index < len(url_pattern) and depth:
            char = url_pattern[index]
            if char == "\\":
                index += 1
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            index += 1

        inner = url_pattern[match.end() : index - 1]
        schema = {"type": "string"}
        try:
            re.compile(inner)
        except re.error:
            pass
        else:
            # Anything matching everything says nothing worth recording.
            if inner not in (".+", ".*", ".+?", ".*?"):
                schema["pattern"] = inner
        params[match["name"]] = {"schema": schema}
        out.append("{%s}" % match["name"])
        pos = index

    def take_converter(conv_match):
        schema = dict(CONVERTERS.get(conv_match["conv"] or "str", {"type": "string"}))
        params[conv_match["name"]] = {"schema": schema}
        return "{%s}" % conv_match["name"]

    path = PATH_CONV.sub(take_converter, "".join(out))
    return "/" + path.lstrip("/"), params


def field_schema(field):
    """Map a DRF serializer field to a schema, walking its base classes."""
    for klass in type(field).__mro__:
        if klass.__name__ in FIELDS:
            schema = dict(FIELDS[klass.__name__])
            break
    else:
        schema = {"type": "string"}
    choices = getattr(field, "choices", None)
    if choices:
        schema["enum"] = list(choices)
    return schema


def nest(items, unknown):
    """Build an object schema from a flat list of possibly dotted field names."""
    properties = {}
    for item in items:
        name = item.get("name")
        if not name or name == "-":
            continue
        declared = item.get("type")
        schema = TYPES.get(declared)
        if schema is None:
            unknown.append((name, declared))
            schema = {"type": "string"}
        schema = dict(schema)
        if item.get("doc"):
            schema["description"] = clean(item["doc"])

        target = properties
        *parents, leaf = name.split(".")
        for parent in parents:
            node = target.setdefault(parent, {"type": "object", "properties": {}})
            node.setdefault("properties", {})
            target = node["properties"]
        target[leaf] = schema
    return {"type": "object", "properties": properties} if properties else None


def clean(text):
    """Flatten a reStructuredText fragment into a plain description."""
    text = re.sub(r"\.\.\s+\w+::\s*", "", text)
    text = re.sub(r"`([^`<]+?)\s*<[^>]+>`_", r"\1", text)
    text = re.sub(r"``([^`]+)``", r"\1", text)
    text = re.sub(r":http:\w+:`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return " ".join(text.split())


def summarise(description):
    """First sentence of a description, as swh-web's own endpoint index uses."""
    return re.split(r"\.\s", clean(description), maxsplit=1)[0].rstrip(".")


def examples_for(url_pattern, examples):
    """Extract parameter values from the example URLs upstream documents.

    Upstream records examples as whole request URLs rather than as payloads,
    so matching one back against its own route recovers a real value for each
    path and query parameter.
    """
    values = {}
    pattern = re.compile("^/?" + url_pattern.rstrip("/") + "/?$")
    for example in examples:
        path, _, query = example.partition("?")
        match = pattern.match(path)
        if match:
            values.update({k: v for k, v in (match.groupdict() or {}).items() if v})
        for pair in query.split("&"):
            name, sep, value = pair.partition("=")
            if sep and name not in values:
                values[name] = urllib.parse.unquote(value)
    return values
