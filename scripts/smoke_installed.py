"""Smoke test of an installed vkworkspace (a built wheel or sdist), used by the release job.

Run it from a directory that is not the repository: it fails when the package
is imported from the sources.
"""

import pathlib
import sys

import vkworkspace
from vkworkspace import Bot, Dispatcher, make_ssl_context

location = pathlib.Path(vkworkspace.__file__).resolve()
sources = pathlib.Path(__file__).resolve().parent.parent
if sources in location.parents:
    sys.exit(f"vkworkspace was imported from the sources: {location}")

Dispatcher()
Bot(token="smoke", api_url="https://example.invalid/bot/v1")
make_ssl_context(mincifry=True)  # reads the certificate shipped inside the package
print(f"vkworkspace {vkworkspace.__version__} from {location.parent}")
