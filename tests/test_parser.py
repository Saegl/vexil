import pathlib
from parser import parse


def test_examples():
    examples_dir = pathlib.Path("noname_examples/")

    for file in examples_dir.rglob("*.noname"):
        parse(file)
