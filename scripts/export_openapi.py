"""Export OpenAPI schema to JSON file."""
import json
import sys

sys.path.insert(0, "src")

from app.main import app  # noqa: E402

schema = app.openapi()
output = "openapi.json"
with open(output, "w") as f:
    json.dump(schema, f, indent=2)

print(f"OpenAPI schema exported to {output}")
