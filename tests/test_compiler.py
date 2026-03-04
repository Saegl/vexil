from pathlib import Path

from compiler import Compiler
from parser import parse_program
from vexil import load_program_with_imports


def test_build_examples_folder() -> None:
    examples_dir = Path(__file__).resolve().parents[1] / "examples"
    for path in examples_dir.glob("*.vx"):
        program = load_program_with_imports(path)
        compiler = Compiler()
        compiler.compile_program(program)


def test_compile_float_print() -> None:
    src = "def main() { let x: float = 1.5; print(x) }"
    program = parse_program(src)
    compiler = Compiler()
    module = compiler.compile_program(program)
    ir_text = str(module)
    assert "print_float" in ir_text


def test_compile_string_format() -> None:
    src = 'def main() { let name: string = "A"; print("Hello, {}!".format(name)) }'
    program = parse_program(src)
    compiler = Compiler()
    module = compiler.compile_program(program)
    ir_text = str(module)
    assert "format1" in ir_text


def test_compile_enum_match() -> None:
    src = (
        "enum Shape {\n"
        "  Circle(int)\n"
        "  Point\n"
        "}\n"
        "def area(s: Shape) -> int {\n"
        "  return match s {\n"
        "    Circle(r) => r * r\n"
        "    Point => 0\n"
        "  }\n"
        "}\n"
        "def main() { let s = Shape.Circle(3); print(area(s)) }\n"
    )
    program = parse_program(src)
    compiler = Compiler()
    module = compiler.compile_program(program)
    ir_text = str(module)
    assert "area" in ir_text


def test_compile_class_methods() -> None:
    src = (
        "class Counter { value: int\n"
        "  def init(self, value: int) { self.value = value }\n"
        "  def inc(self) -> int { self.value = self.value + 1; return self.value }\n"
        "}\n"
        "def main() { let c = Counter(1); print(c.inc()) }\n"
    )
    program = parse_program(src)
    compiler = Compiler()
    module = compiler.compile_program(program)
    ir_text = str(module)
    assert "Counter__init" in ir_text
    assert "Counter__inc" in ir_text
