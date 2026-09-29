"""Django settings for OpenAPI schema generation.

Built on swh-web's own settings so the schema comes from the same URLconf and
serializers the application serves. ``common`` rather than ``development``:
the development module calls ``cache.clear()`` while the settings module is
still being imported, which initialises the cache handler before ``CACHES``
exists and breaks every management command.
"""

from swh.web.settings.common import *  # noqa: F401,F403
from swh.web.settings.common import INSTALLED_APPS, SWH_BASE_DJANGO_APPS

# Endpoints live across several swh-web apps. Only swh.web.api is enabled by
# default; the rest are opted into per deployment, and the public archive runs
# all of them.
SWH_API_DJANGO_APPS = [
    "swh.web.add_forge_now",
    "swh.web.provenance",
    "swh.web.save_bulk",
    "swh.web.save_code_now",
    "swh.web.save_origin_webhooks",
    "swh.web.vault",
    "swh.web.vulns",
]

_extra = [app for app in SWH_API_DJANGO_APPS if app not in INSTALLED_APPS]

SWH_DJANGO_APPS = SWH_BASE_DJANGO_APPS + [
    app for app in SWH_API_DJANGO_APPS if app not in SWH_BASE_DJANGO_APPS
]
INSTALLED_APPS = list(INSTALLED_APPS) + _extra
