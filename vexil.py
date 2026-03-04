from __future__ import annotations

from parser import parse_program


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Parse Vexil source file.")
    parser.add_argument("path", nargs="?", help="Path to .vx file")
    args = parser.parse_args()

    if not args.path:
        return

    with open(args.path, "r", encoding="utf-8") as handle:
        source = handle.read()
    ast = parse_program(source)
    print(ast)


if __name__ == "__main__":
    main()
