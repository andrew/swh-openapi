"""Apply an OpenAPI Overlay 1.0 document to a generated description.

The generated description is regenerated from scratch whenever swh-web moves,
so corrections to it live in a separate overlay rather than as edits that the
next run would discard. See https://spec.openapis.org/overlay/v1.0.0.html
"""

import argparse
import copy

import jsonpath_ng.ext
import yaml


class Dumper(yaml.SafeDumper):
    """Repeat shared objects rather than emitting YAML anchors."""

    def ignore_aliases(self, data):
        return True


def merge(target, update):
    """Merge an update into a target object, recursing into nested maps."""
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = value


def apply(document, overlay):
    """Apply each of an overlay's actions in order, returning a new document."""
    document = copy.deepcopy(document)
    applied = []
    for index, action in enumerate(overlay.get("actions", [])):
        expression = jsonpath_ng.ext.parse(action["target"])
        matches = expression.find(document)
        for match in matches:
            if action.get("remove"):
                del match.context.value[match.path.fields[0]]
            else:
                merge(match.value, action["update"])
        applied.append((index, action["target"], len(matches)))
    return document, applied


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generated")
    parser.add_argument("overlay")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    with open(args.generated) as f:
        document = yaml.safe_load(f)
    with open(args.overlay) as f:
        overlay = yaml.safe_load(f) or {"actions": []}

    merged, applied = apply(document, overlay)

    with open(args.output, "w") as f:
        yaml.dump(merged, f, Dumper=Dumper, sort_keys=False, width=100, allow_unicode=True)

    for index, target, count in applied:
        status = "ok" if count else "MATCHED NOTHING"
        print(f"action {index}: {count} match(es) {status}  {target}")


if __name__ == "__main__":
    main()
