"""Headless render check for every dashboard page."""
from streamlit.testing.v1 import AppTest

NAMES = ["Portfolio", "Research", "Risk", "Performance", "Execution", "Letter"]
for i, name in enumerate(NAMES):
    at = AppTest.from_file("dashboard/app.py", default_timeout=120)
    at.query_params["page"] = str(i)
    at.run()
    status = "OK" if not at.exception else "ERROR: " + str(at.exception)
    print(f"page {i} ({name}): {status}")
