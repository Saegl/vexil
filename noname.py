from __future__ import annotations

import argparse
from io import TextIOWrapper
import pathlib
import subprocess
from pprint import pprint

import parser


class Codegen:
    var_offsets: dict[str, int]
    last_offset: int

    def __init__(self) -> None:
        self.var_offsets = {}
        self.last_offset = -4

    def codegen_expr(self, output: TextIOWrapper, expr: parser.Expr) -> str:
        match expr:
            case parser.IntLiteral(i):
                output.write(f"\tmovl\t${i}, %eax\t# load int literal\n")
                return "%eax"

            case parser.Var(name):
                offset = self.var_offsets[name]
                output.write(f"\tmovl\t{offset}(%rbp), %eax\t# load var '{name}'\n")
                return "%eax"

            case parser.BinOp(lhs, op, rhs):
                ops = {
                    "+": "addl",
                    "-": "subl",
                    "*": "imull",
                }
                op_cmd = ops[op]

                self.codegen_expr(output, lhs)
                output.write(f"\tpushq\t%rax\t\t# save lhs for {op}\n")

                self.codegen_expr(output, rhs)

                output.write("\tmovl\t%eax, %ecx\t# move rhs to 'ecx'\n")
                output.write(f"\tpopq\t%rax\t\t# restore lhs for {op}\n")
                output.write(f"\t{op_cmd}\t%ecx, %eax\t# do {op}\n")

                return "%eax"

            case other:
                raise Exception(f"Unexpected Expr {other}")

    def codegen(self, filename: str, fn: parser.Function) -> None:
        output = open("program.s", "w")

        output.write(f'\t.file\t"{filename}"\n')
        output.write("\t.text\n")  # code section
        output.write("\t.globl\tmain\n")  # main accessible by linker
        output.write("\t.type\tmain, @function\n")  # main is function, for linker

        output.write(f"{fn.name}:\n")  # label where function starts
        # save %rbp value in stack, to restore it in the end
        output.write("\t# save stack\n")
        output.write("\tpushq\t%rbp\n")
        # establish new stack frame for `main`
        output.write("\tmovq\t%rsp, %rbp\n")
        output.write("\n")

        for statement in fn.block.statements:
            match statement:
                case parser.Return(expr):
                    value = self.codegen_expr(output, expr)
                    output.write(f"\tmovl\t{value}, %eax\t# return\n")
                case parser.DeclVariable(name, parser.IntLiteral(i)):
                    self.var_offsets[name] = self.last_offset
                    self.last_offset -= 4
                    output.write(
                        f"\tmovl\t${i}, {self.var_offsets[name]}(%rbp)\t# decl '{name}'\n"
                    )
                case other:
                    raise Exception(f"Unexpected stmt {other}")

        output.write("\n\t# restore stack\n")
        output.write("\tpopq\t%rbp\n")  # restore previous base pointer from stack
        output.write("\tret\n")  # return control to the caller

        # calculate main function size for debugging
        # ".-main" .(current place) -(minus) main(label)
        output.write("\t.size\tmain, .-main\n")
        output.write('\t.ident\t"NONAME"\n')  # compiler metadata
        # no execution stack is needed
        output.write('\t.section\t.note.GNU-stack,"",@progbits\n')

        output.close()


def main() -> None:
    argparser = argparse.ArgumentParser()
    argparser.add_argument("file", type=pathlib.Path)
    argparser.add_argument("--ast", action="store_true")
    argparser.add_argument("--asm", action="store_true")
    argparser.add_argument("--run", action="store_true")
    args = argparser.parse_args()

    input_file_path = pathlib.Path(args.file)

    fn = parser.parse(input_file_path)
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
        compilation_result = subprocess.run(["gcc", "program.s"])
        if compilation_result.returncode == 0:
            out = subprocess.run(["./a.out"])
            print(out.returncode)


if __name__ == "__main__":
    main()
