from __future__ import annotations

from compiler import Compiler, build_executable
from parser import parse_program


def compile_path(path: "Path") -> "Compiler":
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    program = parse_program(source)
    compiler = Compiler()
    compiler.compile_program(program)
    return compiler


def main() -> None:
    import argparse
    from pathlib import Path
    import subprocess
    import tempfile

    parser = argparse.ArgumentParser(description="Vexil compiler")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_cmd = subparsers.add_parser("build", help="Build a Vexil program")
    build_cmd.add_argument("path", help="Path to .vx file")
    build_cmd.add_argument(
        "-o",
        "--output",
        default="vexil.out",
        help="Output executable path",
    )

    run_cmd = subparsers.add_parser("run", help="Build and run a Vexil program")
    run_cmd.add_argument("path", help="Path to .vx file")

    args = parser.parse_args()

    path = Path(args.path)
    compiler = compile_path(path)

    if args.command == "build":
        build_executable(compiler.module, Path(args.output))
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        exe_path = Path(tmpdir) / "vexil_run"
        build_executable(compiler.module, exe_path)
        subprocess.run([str(exe_path)], check=True)


if __name__ == "__main__":
    main()
