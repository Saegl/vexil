from __future__ import annotations

from compiler import Compiler, build_executable
from parser import parse_program


def main() -> None:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Compile Vexil source file.")
    parser.add_argument("path", help="Path to .vx file")
    parser.add_argument(
        "-o",
        "--output",
        default="vexil.out",
        help="Output executable path",
    )
    args = parser.parse_args()

    path = Path(args.path)

    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    program = parse_program(source)

    compiler = Compiler()
    module = compiler.compile_program(program)
    build_executable(module, Path(args.output))


if __name__ == "__main__":
    main()
