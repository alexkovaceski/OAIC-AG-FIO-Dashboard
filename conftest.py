"""Root pytest conftest: make `src` importable and `site.*` resolve to src/site.

The stdlib `site` module is frozen in CPython 3.13, so src/site can never be
imported as `site.*` through normal sys.path resolution. site_shim.install()
loads the package into sys.modules['site'] before any test collects, so the
plan's import paths (`from site.pages import render_all_pages`) work verbatim.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve() / "src"))

import site_shim  # noqa: E402
site_shim.install()
