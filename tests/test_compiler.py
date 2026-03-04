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


def test_compile_while_loop() -> None:
    src = (
        "def fact(n: int) -> int {\n"
        "    let result = 1\n"
        "    let i = 1\n"
        "    while i <= n {\n"
        "        result = result * i\n"
        "        i = i + 1\n"
        "    }\n"
        "    return result\n"
        "}\n"
        "def main() { print(fact(5)) }\n"
    )
    program = parse_program(src)
    compiler = Compiler()
    module = compiler.compile_program(program)
    ir_text = str(module)
    assert "while.cond" in ir_text
    assert "while.body" in ir_text


def test_compile_and_or_short_circuit() -> None:
    src = (
        "def check(x: int) -> int {\n"
        "    if x > 0 and x < 10 {\n"
        "        return 1\n"
        "    }\n"
        "    if x == 0 or x == 99 {\n"
        "        return 2\n"
        "    }\n"
        "    return 0\n"
        "}\n"
        "def main() { print(check(5)) }\n"
    )
    program = parse_program(src)
    compiler = Compiler()
    module = compiler.compile_program(program)
    ir_text = str(module)
    assert "and.rhs" in ir_text
    assert "or.rhs" in ir_text


def test_compile_not() -> None:
    src = (
        "def flip(x: bool) -> bool {\n"
        "    return not x\n"
        "}\n"
        "def main() { print(flip(true)) }\n"
    )
    program = parse_program(src)
    compiler = Compiler()
    module = compiler.compile_program(program)
    ir_text = str(module)
    assert "flip" in ir_text


def test_compile_for_range() -> None:
    src = (
        "def main() {\n"
        "    let sum = 0\n"
        "    for i in range(10) {\n"
        "        sum = sum + i\n"
        "    }\n"
        "    print(sum)\n"
        "}\n"
    )
    program = parse_program(src)
    compiler = Compiler()
    module = compiler.compile_program(program)
    ir_text = str(module)
    assert "for.cond" in ir_text
    assert "for.body" in ir_text


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
