# swh-openapi

An OpenAPI description of the [Software Heritage](https://www.softwareheritage.org/)
Web API, and the generator that produces it.

Software Heritage does not publish one. Its API reference is built at runtime
from Python docstrings, and the request for a machine-readable format has been
open on their tracker since 2019 as item 4 of
[swh-web#1805](https://gitlab.softwareheritage.org/swh/devel/swh-web/-/work_items/1805).
This repository generates a description from the same data that reference is
built from, so a client can be generated and regenerated as upstream moves.

`openapi.yaml` is the file to use. It currently describes 63 paths and 70
operations across 33 named schemas, generated from swh.web 0.17.12.

Its `info.version` is the CalVer date the description was generated, and
`info.x-swh-web-version` records the swh.web release it came from.

## How it is generated

swh-web decorates each endpoint with `api_doc`, which parses a sphinx
httpdomain docstring into structured data, and `api_route`, which registers the
URL and holds an optional DRF serializer that validates the query parameters.
Neither records what it saw anywhere a later caller can reach, so
`generator/collect.py` wraps both before importing the URLconf and keeps what
passes through. `generator/generate.py` turns that into OpenAPI.

Response and request bodies are hoisted into `components/schemas`, named after
the route that first uses them, so generated clients get named types rather
than anonymous inline structs. swh-web documents many endpoints with shared
docstring fragments, so identical shapes collapse to one schema.

Scraping the published documentation pages is not an alternative. They sit
behind an [Anubis](https://anubis.techaro.lol/) proof-of-work challenge and
return a challenge page with a 200 status. The JSON API itself is not behind
it.

Running drf-spectacular against swh-web instead produces almost nothing: the
endpoints are plain `@api_view` functions with no `serializer_class`, so it
emits 211 operations whose only query parameter is `format` and whose every
200 response is `No response body`.

## Running it

Generation runs in Docker on linux/amd64, because swh.search publishes wheels
for that platform alone and its sdist build wants a JavaScript toolchain. The
image is the full Debian-based `python:3.11` rather than `-slim`, because
swh-web's URLconf imports psycopg and python-magic at module load and so needs
libpq and libmagic present.

    make image      # build the generator image
    make spec       # regenerate openapi.gen.yaml, then apply the overlay
    make validate   # check openapi.yaml against the OpenAPI schema
    make test       # unit tests for the mapping
    make drift      # compare openapi.yaml against the live archive

On Apple Silicon the image builds and runs under emulation, which is slow but
works.

## The three files

`openapi.gen.yaml` is the generator's raw output. Nothing edits it by hand,
because the next run overwrites it.

`overlay.yaml` holds corrections, in the
[OpenAPI Overlay 1.0](https://spec.openapis.org/overlay/v1.0.0.html) format.
Each action targets part of the generated document with a JSONPath expression
and either updates or removes it. Corrections live here so that regenerating
against a new swh.web produces a readable diff on the raw file and leaves the
fixes in place.

`openapi.yaml` is the two merged, and the file clients vendor.

`make overlay` prints the match count for every action, so an action that has
stopped matching anything after an upstream change is visible rather than
silent.

## Updating to a new swh.web

    make image SWH_WEB_VERSION=0.17.13
    make spec  SWH_WEB_VERSION=0.17.13
    make validate

Then read the diff on `openapi.gen.yaml`, which is upstream's documentation
changing, and check that every overlay action still matches.

The weekly `refresh` workflow does this automatically and opens a pull request
when the output moves.

## Drift between releases

The archive publishes its route list as JSON at
`https://archive.softwareheritage.org/api/1/`, with no proof-of-work wall.
`make drift` compares that list against the `x-swh-doc-route` recorded on every
operation, which catches endpoints a deployment added or removed before the
matching swh.web release reaches PyPI. It is a route-level check and says
nothing about changed fields.

## What the description does and does not cover

Paths, methods, path parameters and status codes are reliable. Query
parameters are exact for the 14 endpoints with a `query_params_serializer` and
come from prose for the rest.

Response bodies are the weak part. Upstream describes them one flat level deep,
as a list of scalar fields, with type words applied inconsistently across
`string`, `str`, `number`, `int`, `boolean`, `array`, `object` and `date`.
Nesting is expressed only where a field name contains a dot. Every field
declared `number` upstream is a count or an identifier, so it maps to
`integer`. Anything unmapped falls back to `string` and is reported at the end
of a generation run rather than guessed at.

Three registered endpoints carry no documentation at all and so appear nowhere
in the description: `/api/1/`, `/api/1/graph/{graph_query}/` and
`/api/1/raw-extrinsic-metadata/get/{id}/`. Five more are tagged `hidden`
upstream and are excluded deliberately.

## Using it

A Go client generates cleanly:

    oapi-codegen -package swh -generate models,client openapi.yaml > client.gen.go

For Ruby, the description is more useful as a test fixture than as input to a
generator. Generated Ruby models add little over hashes, and the output is
bulky.

Four things no generated client handles, which a usable one needs:

Pagination is a `Link` header with `rel="next"`. The underlying parameters are
inconsistent per endpoint, `limit` and `page_token` on origin search against
`per_page` and `last_visit` on origin visits, so follow the header rather than
modelling each scheme.

Rate limits vary by endpoint, not only by whether you are authenticated.
Anonymous `X-RateLimit-Limit` is 120 on most routes and 10 on
`/api/1/origin/search/`. `X-RateLimit-Reset` is a unix timestamp.

Authentication is an OpenID Connect bearer token from the Software Heritage
Keycloak realm, obtained by exchanging a long-lived offline token at
`https://auth.softwareheritage.org/auth/realms/SoftwareHeritage/protocol/openid-connect/token`
with the `refresh_token` grant and client id `swh-web`.

Vault cooking and Save Code Now are asynchronous and need polling.

There is also a GraphQL API at `https://archive.softwareheritage.org/graphql/`
with introspection enabled, covering the archive traversal half of the surface
across 13 root query fields. It has no vault, Save Code Now, provenance or
counters. Where it fits, its schema needs no generator at all.

## Licensing

The generator is AGPL-3.0-or-later, in `LICENSE`, matching swh-web, which it
imports.

The generated description is CC0-1.0, in `LICENSE.spec`, so that clients can
vendor it without friction.
