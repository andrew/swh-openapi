"""Compare a description against the endpoint index the live archive serves.

The archive publishes its route list as JSON at /api/1/, without the
proof-of-work wall that guards the HTML documentation pages. Comparing against
it catches endpoints added or removed by a deployment before the corresponding
swh.web release reaches PyPI.
"""

import argparse
import json
import sys
import urllib.request

import yaml

INDEX_URL = "https://archive.softwareheritage.org/api/1/"


def live_routes(url):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        index = json.load(response)
    return {
        entry["route"]
        for _, entries in index["doc_routes"]
        for entry in entries
    }


def described_routes(path):
    with open(path) as f:
        document = yaml.safe_load(f)
    return {
        operation["x-swh-doc-route"]
        for item in document["paths"].values()
        for operation in item.values()
        if "x-swh-doc-route" in operation
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec")
    parser.add_argument("--url", default=INDEX_URL)
    args = parser.parse_args()

    live = live_routes(args.url)
    described = described_routes(args.spec)

    missing = sorted(live - described)
    extra = sorted(described - live)

    print(f"{len(live)} routes live, {len(described)} described")
    for route in missing:
        print(f"  only live:      {route}")
    for route in extra:
        print(f"  only described: {route}")

    return 1 if missing or extra else 0


if __name__ == "__main__":
    sys.exit(main())
