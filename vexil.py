from __future__ import annotations

from pathlib import Path

from compiler import Compiler, build_executable
from parser import FromImportStmt, ImportStmt, Program, parse_program


def resolve_import_path(raw: str, base_dir: "Path", stdlib_dir: "Path") -> "Path":
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    if raw.startswith("."):
        return (base_dir / raw).resolve()
    # Try relative to module, then stdlib
    local = (base_dir / raw).resolve()
    if local.exists():
        return local
    return (stdlib_dir / raw).resolve()


def load_program_with_imports(path: "Path") -> Program:
    stdlib_dir = Path(__file__).resolve().parent / "stdlib"
    seen: set[Path] = set()
    ordered: list[Program] = []

    def visit(file_path: Path) -> None:
        file_path = file_path.resolve()
        if file_path in seen:
            return
        seen.add(file_path)
        source = file_path.read_text(encoding="utf-8")
        program = parse_program(source)
        base_dir = file_path.parent
        for stmt in program.statements:
            if isinstance(stmt, ImportStmt):
                import_path = resolve_import_path(stmt.path, base_dir, stdlib_dir)
                visit(import_path)
            elif isinstance(stmt, FromImportStmt):
                import_path = resolve_import_path(stmt.path, base_dir, stdlib_dir)
                visit(import_path)
        ordered.append(program)

    visit(path)

    combined = []
    for program in ordered:
        for stmt in program.statements:
            if isinstance(stmt, (ImportStmt, FromImportStmt)):
                continue
            combined.append(stmt)
    return Program(combined)


def compile_path(path: "Path") -> "Compiler":
    program = load_program_with_imports(path)
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
