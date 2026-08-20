"""Run the FOI Insights POC: python scripts/serve.py (uvicorn on :8095 or :FOI_PORT)."""
import sys, os
sys.path.insert(0, "src")
import site_shim
site_shim.install()  # must precede importing server.app (which imports site.*)
import uvicorn
from server.app import create_app

if __name__ == "__main__":
    port = int(os.environ.get("FOI_PORT", "8095"))
    uvicorn.run(create_app(), host="0.0.0.0", port=port)
