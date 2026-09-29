"""Collect endpoint metadata from swh-web.

swh-web builds its API docs at runtime from two decorators. ``api_doc`` parses
each endpoint's sphinx httpdomain docstring into structured data; ``api_route``
registers the URL and holds an optional DRF serializer validating the query
parameters. Neither records what it saw anywhere reachable afterwards, so both
are wrapped here before the URLconf is imported and the decorated views built.
"""

import collections

import django

# Endpoints apply the two decorators in either order, so each wrapper leaves a
# marker on the function for whichever runs second to pick up. functools.wraps
# copies __dict__, so the markers survive the wrappers in between.
ROUTE_ATTR = "__swh_openapi_route__"
PENDING_ATTR = "__swh_openapi_pending__"


def collect():
    """Import swh-web's URLconf and describe every registered API endpoint.

    Returns a list of records, one per URL pattern, and a list of registrations
    carrying no documentation at all.
    """
    django.setup()

    from swh.web.api import apidoc, apiurls

    # A documented route can carry several URL patterns: /directory/ is served
    # both with and without a trailing path, /origin/save/ has three.
    registrations = collections.defaultdict(list)
    all_registrations = []
    documented = {}

    real_api_route = apiurls.api_route
    real_api_doc = apidoc.api_doc

    def api_route(url_pattern, view_name, methods=None, **kwargs):
        passed = dict(kwargs)
        if methods is not None:
            passed["methods"] = methods
        decorator = real_api_route(url_pattern, view_name, **passed)

        def wrapper(f):
            registration = {
                "url_pattern": "api/" + kwargs.get("api_version", "1") + url_pattern,
                "view_name": view_name,
                "methods": methods or ["GET", "HEAD", "OPTIONS"],
                "serializer": kwargs.get("query_params_serializer"),
            }
            all_registrations.append(registration)
            route = getattr(f, ROUTE_ATTR, None)
            if route is not None:
                registrations[route].append(registration)
            else:
                f.__dict__.setdefault(PENDING_ATTR, []).append(registration)
            return decorator(f)

        return wrapper

    def api_doc(route, *, category, noargs=False, tags=[], api_version="1"):
        decorator = real_api_doc(
            route, category=category, noargs=noargs, tags=tags, api_version=api_version
        )

        def wrapper(f):
            setattr(f, ROUTE_ATTR, route)
            registrations[route].extend(f.__dict__.pop(PENDING_ATTR, []))
            documented[route] = {
                "func": f,
                "route": route,
                "noargs": noargs,
                "category": category,
                "tags": set(tags),
                "api_version": api_version,
            }
            return decorator(f)

        return wrapper

    apiurls.api_route = api_route
    apidoc.api_doc = api_doc
    try:
        import swh.web.urls  # noqa: F401
    finally:
        apiurls.api_route = real_api_route
        apidoc.api_doc = real_api_doc

    records = []
    for route, entry in documented.items():
        doc_data = apidoc.get_doc_data(entry["func"], route, entry["noargs"])
        for registration in registrations[route]:
            records.append({**entry, **registration, "doc_data": doc_data})

    claimed = {id(r) for rs in registrations.values() for r in rs}
    undocumented = [r for r in all_registrations if id(r) not in claimed]
    return records, undocumented
