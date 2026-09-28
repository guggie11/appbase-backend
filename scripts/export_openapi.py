#!/usr/bin/env python3
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def export_openapi():
    from app.main import app
    schema = app.openapi()
    output = Path(__file__).parent.parent / "openapi.json"
    output.write_text(json.dumps(schema, indent=2, ensure_ascii=False))
    print(f"Exported {len(schema.get('paths', {}))} endpoints to {output}")

if __name__ == "__main__":
    export_openapi()
