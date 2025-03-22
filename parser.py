from __future__ import annotations
import pathlib
import dataclasses
import typing
from pcomb import Parser, char, choice, Source, keyword, ws, ws1


@dataclasses.dataclass
class Block:
    statements: list


@dataclasses.dataclass
class Function:
    name: str
    block: Block


@dataclasses.dataclass
class Statement:
    pass


@dataclasses.dataclass
class Return(Statement):
    value: "Expr"


@dataclasses.dataclass
class DeclVariable(Statement):
    name: str
    expr: Expr


@dataclasses.dataclass
class Expr:
    pass


@dataclasses.dataclass
class IntLiteral(Expr):
    val: int


@dataclasses.dataclass
class Var(Expr):
    name: str


@dataclasses.dataclass
class BinOp(Expr):
    lhs: Expr
    op: str
    rhs: Expr


@Parser
def newline(s: Source):
    parser = char("\n")
    parser(s).unwrap()


@Parser
def fn_params(s: Source):
    left_paren = char("(")
    left_paren(s).unwrap()

    right_paren = char(")")
    right_paren(s).unwrap()


@Parser
def integer(s: Source) -> IntLiteral:
    ans = ""
    while "0" <= s.peek() <= "9":
        ans += s.peek()
        s.pos += 1

    return IntLiteral(int(ans))


@Parser
def indent(s: Source) -> str:
    ans = ""
    while "a" <= s.peek() <= "z":
        ans += s.peek()
        s.pos += 1

    return ans


@Parser
def variable(s: Source) -> Var:
    ans = ""
    while "a" <= s.peek() <= "z":
        ans += s.peek()
        s.pos += 1

    return Var(ans)


@Parser
def binop(s: Source) -> BinOp:
    lhs = integer(s).unwrap()
    ws(s).unwrap()

    op = choice(char("+"), char("-"), char("*"))(s).unwrap()
    ws(s).unwrap()

    rhs = integer(s).unwrap()
    return BinOp(lhs, op, rhs)


@Parser
def expr(s: Source) -> Expr:
    choices: list[Parser[Expr]] = typing.cast(
        list[Parser[Expr]],
        [
            binop,
            integer,
            variable,
        ],
    )
    expr_parser = choice(*choices)
    expr = expr_parser(s)
    return expr.unwrap()


@Parser
def return_stmt(s: Source) -> Return:
    keyword("return")(s).unwrap()
    ws1(s).unwrap()
    value = expr(s).unwrap()
    return Return(value)


@Parser
def decl_stmt(s: Source) -> DeclVariable:
    keyword("let")(s).unwrap()
    ws1(s).unwrap()

    varname = indent(s).unwrap()
    ws1(s).unwrap()

    char("=")(s).unwrap()
    ws1(s).unwrap()

    e = expr(s).unwrap()

    return DeclVariable(name=varname, expr=e)


@Parser
def stmt(s: Source) -> Statement:
    choices: list[Parser[Statement]] = typing.cast(
        list[Parser[Statement]], [return_stmt, decl_stmt]
    )
    stmt_parser = choice(*choices)
    stmt = stmt_parser(s)
    out = stmt.unwrap()
    ws(s).unwrap()
    newline(s).unwrap()
    return out


@Parser
def block(s: Source) -> Block:
    char("{")(s).unwrap()
    newline(s).unwrap()

    statements = []

    while True:
        ws(s).unwrap()
        statement = stmt(s)
        if statement.is_succ():
            statements.append(statement.unwrap())
        else:
            break

    ws(s).unwrap()
    char("}")(s).unwrap()

    return Block(statements)


@Parser
def function(s: Source):
    keyword("fn")(s).unwrap()
    ws(s).unwrap()

    name = indent(s).unwrap()
    ws(s).unwrap()

    fn_params(s)
    ws(s).unwrap()

    fn_block = block(s).unwrap()

    return Function(name=name, block=fn_block)


def parse(filepath: pathlib.Path):
    source = filepath.read_text()
    f = function(Source(source)).unwrap()
    return f
