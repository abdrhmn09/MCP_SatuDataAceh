"""Generate the shared allowlist from a downloaded official BPS OpenAPI YAML.

Usage: python update_bps_registry.py /path/to/openapi.yaml
Development dependency: PyYAML (not needed by the MCP runtime).
Review the generated diff and run both test suites before deploying.
"""
import argparse
import json
from pathlib import Path


def main():
    try:
        import yaml
    except ImportError:
        raise SystemExit("Install development dependency first: python3 -m pip install pyyaml")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "src/bps_operations.json")
    args = parser.parse_args()
    spec = yaml.safe_load(args.spec.read_text(encoding="utf-8"))
    operations = {}
    for path, methods in spec["paths"].items():
        if "get" not in methods:
            continue
        if not path.startswith(("/v1/api/", "/v1/searching/", "/v1/sdgs")) or "?" in path or "#" in path:
            raise ValueError(f"Unexpected API path; review manually: {path}")
        operation = methods["get"]
        parameters = []
        for parameter in operation.get("parameters", []):
            if "$ref" in parameter:
                parameter = spec["components"]["parameters"][parameter["$ref"].split("/")[-1]]
            if parameter["name"] in {"key", "Token"}:
                continue
            parameters.append({k: parameter[k] for k in ("name", "in", "required", "description", "schema") if k in parameter})
        operations[operation["operationId"]] = {
            "path": path, "summary": operation["summary"], "group": operation["tags"][0],
            "credential": "sdgs" if path.startswith("/v1/sdgs") else "bps", "parameters": parameters,
        }
    args.output.write_text(json.dumps({"source": "https://webapi.bps.go.id/documentation/openapi.yaml", "operations": operations}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(operations)} GET operations. Review schema changes before deployment.")


if __name__ == "__main__":
    main()
