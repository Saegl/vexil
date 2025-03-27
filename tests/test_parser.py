import pathlib
from parser import parse


def test_examples():
    examples_dir = pathlib.Path("vexil_examples/")

    for file in examples_dir.rglob("*.vexil"):
        parse(file)
