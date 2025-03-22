from __future__ import annotations

import argparse
from io import TextIOWrapper
import pathlib
import dataclasses
import typing
import subprocess
from pprint import pprint
from pcomb import Parser, char, choice, Source, keyword, ws, ws1


@dataclasses.dataclass
class Block:
    statements: list


@dataclasses.dataclass
class Function:
    name: str
    block: Block


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

    op = char("+")(s).unwrap()
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


class Codegen:
    def __init__(self):
        self.var_offsets = {}
        self.last_offset = -4

    def codegen_expr(self, output: TextIOWrapper, expr: Expr):
        match expr:
            case IntLiteral(i):
                output.write(f"\tmovl\t${i}, %eax\n")
                return "%eax"
            case Var(name):
                return f"{self.var_offsets[name]}(%rbp)"
            case BinOp(IntLiteral(lhs), "+", IntLiteral(rhs)):
                output.write(f"\tmovl\t${lhs}, %eax\n")
                output.write(f"\taddl\t${rhs}, %eax\n")
                return "%eax"
            case other:
                raise Exception(f"Unexpected Expr {other}")

    def codegen(self, filename: str, fn: Function):
        output = open("program.s", "w")

        output.write(f'\t.file\t"{filename}"\n')
        output.write("\t.text\n")  # code section
        output.write("\t.globl\tmain\n")  # main accessible by linker
        output.write("\t.type\tmain, @function\n")  # main is function, for linker

        output.write(f"{fn.name}:\n")  # label where function starts
        # save %rbp value in stack, to restore it in the end
        output.write("\tpushq\t%rbp\n")
        # establish new stack frame for `main`
        output.write("\tmovq\t%rsp, %rbp\n")

        for statement in fn.block.statements:
            match statement:
                case Return(expr):
                    value = self.codegen_expr(output, expr)
                    output.write(f"\tmovl\t{value}, %eax\n")
                case DeclVariable(name, IntLiteral(i)):
                    self.var_offsets[name] = self.last_offset
                    self.last_offset -= 4
                    output.write(f"\tmovl\t${i}, {self.var_offsets[name]}(%rbp)\n")
                case other:
                    raise Exception(f"Unexpected stmt {other}")

        output.write("\tpopq\t%rbp\n")  # restore previous base pointer from stack
        output.write("\tret\n")  # return control to the caller

        # calculate main function size for debugging
        # ".-main" .(current place) -(minus) main(label)
        output.write("\t.size\tmain, .-main\n")
        output.write('\t.ident\t"NONAME"\n')  # compiler metadata
        # no execution stack is needed
        output.write('\t.section\t.note.GNU-stack,"",@progbits\n')

        output.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=pathlib.Path)
    parser.add_argument("--ast", action="store_true")
    parser.add_argument("--asm", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()

    input_file_path = pathlib.Path(args.file)

    fn = parse(input_file_path)
    if args.ast:
        print("\n===AST===")
        pprint(fn)

    codegen = Codegen()
    codegen.codegen(input_file_path.name, fn)

    if args.asm:
        print("\n===ASM===")
        print(pathlib.Path("program.s").read_text())

    if args.run:
        print("\n===RUN===")
        subprocess.run(["gcc", "program.s"])
        out = subprocess.run(["./a.out"])
        print(out.returncode)


if __name__ == "__main__":
    main()
