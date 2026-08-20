"""site_shim — make `site.*` resolve to the src/site package, not the stdlib.

CPython 3.13 freezes the stdlib `site` module (origin 'frozen'); the frozen
importer owns the top-level name, so a `src/site` package can never be imported
as `site.*` through normal sys.path resolution — `from site.pages import ...`
would always hit the stdlib module. `install()` loads src/site into
sys.modules['site'] under the frozen name, so the plan's import paths
(`from site.pages import render_all_pages`) work verbatim.

Call install() once at process start in any entry point that imports site.* —
pytest does this automatically via the root conftest.py; the Task 8 server
(start of src/server/app.py or scripts/serve.py) needs the same one-liner:
    import site_shim; site_shim.install()
"""
from __future__ import annotations
import importlib.util
import pathlib
import sys

_SITE_DIR = pathlib.Path(__file__).resolve().parent / "site"


def install():
    """Install src/site as sys.modules['site'] (idempotent). Returns the package."""
    existing = sys.modules.get("site")
    if existing is not None and getattr(existing, "__path__", None):
        return existing                       # our package is already installed
    spec = importlib.util.spec_from_file_location(
        "site", _SITE_DIR / "__init__.py", submodule_search_locations=[str(_SITE_DIR)])
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["site"] = pkg                 # shadow the frozen stdlib name
    spec.loader.exec_module(pkg)
    return pkg
