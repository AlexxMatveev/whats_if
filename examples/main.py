#!/usr/bin/env python3
"""
ArchOps YAML → draw.io C4 reverse parser
Reads ArchOps manifests and generates draw.io XML with C4 notation.
Mirrors the mappings from the original drawio-to-archops Go parser.
"""

import argparse
import sys
from pathlib import Path

from parser.yaml_loader import YamlLoader
from parser.drawio_generator import DrawioGenerator


def main():
    ap = argparse.ArgumentParser(
        description="Convert ArchOps YAML manifests to draw.io C4 diagram"
    )
    ap.add_argument(
        "--input",
        required=True,
        help="Path to a single YAML file OR directory with YAML manifests",
    )
    ap.add_argument(
        "--output",
        default="diagram.drawio",
        help="Output draw.io file path (default: diagram.drawio)",
    )
    ap.add_argument(
        "--type",
        choices=["container", "context", "component"],
        default="container",
        help="Diagram type (default: container)",
    )
    args = ap.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: input path does not exist: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Load all YAML manifests
    loader = YamlLoader()
    if input_path.is_dir():
        manifests = loader.load_directory(input_path)
    else:
        manifests = loader.load_file(input_path)

    if not manifests:
        print("ERROR: no ArchOps manifests found", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(manifests)} manifest(s)")

    # Generate draw.io XML
    generator = DrawioGenerator(diagram_type=args.type)
    xml_content = generator.generate(manifests)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml_content, encoding="utf-8")

    print(f"Generated: {output_path}")


if __name__ == "__main__":
    main()