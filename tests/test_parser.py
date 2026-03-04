from pathlib import Path

from parser import (
    Assign,
    Binary,
    Call,
    ClassDef,
    EnumDef,
    ExprStmt,
    FromImportStmt,
    FuncDef,
    IfStmt,
    ImportStmt,
    LetDecl,
    Literal,
    MatchExpr,
    Program,
    ReturnStmt,
    Unary,
    Var,
    WhileStmt,
    parse_program,
)


def test_parse_hello() -> None:
    src = 'def main() {\n    print("Hello, World")\n}\n'
    ast = parse_program(src)
    assert isinstance(ast, Program)
    assert len(ast.statements) == 1
    fn = ast.statements[0]
    assert isinstance(fn, FuncDef)
    assert fn.name == "main"
    assert fn.body.statements
    call_stmt = fn.body.statements[0]
    assert isinstance(call_stmt, ExprStmt)
    assert isinstance(call_stmt.expr, Call)


def test_parse_let_and_const() -> None:
    src = "let x: int = 1\nconst PI = 3.14\n"
    ast = parse_program(src)
    let_stmt = ast.statements[0]
    const_stmt = ast.statements[1]
    assert isinstance(let_stmt, LetDecl)
    assert let_stmt.name == "x"
    assert let_stmt.is_const is False
    assert isinstance(const_stmt, LetDecl)
    assert const_stmt.name == "PI"
    assert const_stmt.is_const is True


def test_parse_imports() -> None:
    src = 'import "math.vx"\nfrom "math.vx" import add, sub\n'
    ast = parse_program(src)
    assert isinstance(ast.statements[0], ImportStmt)
    assert ast.statements[0].path == "math.vx"
    assert isinstance(ast.statements[1], FromImportStmt)
    assert ast.statements[1].path == "math.vx"
    assert ast.statements[1].names == ["add", "sub"]


def test_parse_class_and_enum() -> None:
    src = (
        "class User {\n"
        "    name: string\n"
        "    def init(name: string) {\n"
        "        return\n"
        "    }\n"
        "}\n"
        "enum Shape {\n"
        "    Circle(float)\n"
        "    Point\n"
        "}\n"
    )
    ast = parse_program(src)
    cls = ast.statements[0]
    enm = ast.statements[1]
    assert isinstance(cls, ClassDef)
    assert cls.name == "User"
    assert cls.fields[0].name == "name"
    assert cls.methods and isinstance(cls.methods[0], FuncDef)
    assert isinstance(enm, EnumDef)
    assert enm.variants[0].name == "Circle"
    assert enm.variants[1].name == "Point"


def test_parse_match_and_if() -> None:
    src = (
        "def area(s: Shape) -> float {\n"
        "    if s == s {\n"
        "        return match s {\n"
        "            Point => 0\n"
        "            Circle(r) => r\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    ast = parse_program(src)
    fn = ast.statements[0]
    assert isinstance(fn, FuncDef)
    if_stmt = fn.body.statements[0]
    assert isinstance(if_stmt, IfStmt)
    ret_stmt = if_stmt.then_block.statements[0]
    assert isinstance(ret_stmt, ReturnStmt)
    assert isinstance(ret_stmt.value, MatchExpr)


def test_parse_while() -> None:
    src = (
        "def main() {\n"
        "    let x = 0\n"
        "    while x < 10 {\n"
        "        x = x + 1\n"
        "    }\n"
        "}\n"
    )
    ast = parse_program(src)
    fn = ast.statements[0]
    assert isinstance(fn, FuncDef)
    while_stmt = fn.body.statements[1]
    assert isinstance(while_stmt, WhileStmt)
    assert while_stmt.body.statements


def test_parse_logical_operators() -> None:
    src = (
        "def main() {\n"
        "    let x = true and false\n"
        "    let y = x or true\n"
        "    let z = not x\n"
        "}\n"
    )
    ast = parse_program(src)
    fn = ast.statements[0]
    assert isinstance(fn, FuncDef)
    stmt_and = fn.body.statements[0]
    assert isinstance(stmt_and, LetDecl)
    assert isinstance(stmt_and.value, Binary)
    assert stmt_and.value.op == "and"
    stmt_or = fn.body.statements[1]
    assert isinstance(stmt_or, LetDecl)
    assert isinstance(stmt_or.value, Binary)
    assert stmt_or.value.op == "or"
    stmt_not = fn.body.statements[2]
    assert isinstance(stmt_not, LetDecl)
    assert isinstance(stmt_not.value, Unary)
    assert stmt_not.value.op == "not"


def test_parse_assignment_expr() -> None:
    src = "def main() { x = 1 }"
    ast = parse_program(src)
    fn = ast.statements[0]
    assert isinstance(fn, FuncDef)
    expr_stmt = fn.body.statements[0]
    assert isinstance(expr_stmt, ExprStmt)
    assert isinstance(expr_stmt.expr, Assign)
    assert isinstance(expr_stmt.expr.target, Var)
    assert isinstance(expr_stmt.expr.value, Literal)


def test_parse_examples_folder() -> None:
    examples_dir = Path(__file__).resolve().parents[1] / "examples"
    for path in examples_dir.glob("*.vx"):
        parse_program(path.read_text(encoding="utf-8"))
