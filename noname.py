import argparse
import pathlib
import dataclasses
import string


@dataclasses.dataclass
class Block:
    statements: list


@dataclasses.dataclass
class Function:
    name: str
    block: Block


class Source:
    def __init__(self, source):
        self.source = source
        self.i = 0

    def char(self):
        return self.source[self.i]


def parse_ws(s: Source):
    while s.i < len(s.source) and s.char() in [" ", "\t"]:
        s.i += 1


def parse_char(s: Source):
    char = s.char()
    s.i += 1
    return char


def parse_integer(s: Source) -> int:
    ans = ""
    while s.i < len(s.source) and s.char() in string.digits:
        ans += s.char()
        s.i += 1
    return int(ans)


def parse_indent(s: Source) -> str:
    ans = ""
    while s.i < len(s.source) and s.char() in string.ascii_letters:
        ans += s.char()
        s.i += 1
    return ans


def parse_newline(s: Source):
    char = parse_char(s)
    assert char == "\n"


def parse_params(s: Source):
    left_paren = s.char()
    assert left_paren == "("
    s.i += 1

    right_paren = s.char()
    assert right_paren == ")"
    s.i += 1


def parse_statement(s) -> int:
    return_keyword = parse_indent(s)
    assert return_keyword == "return"
    parse_ws(s)
    integer = parse_integer(s)
    parse_ws(s)
    parse_newline(s)
    parse_ws(s)
    return integer


def parse_block(s: Source) -> Block:
    left_curly = parse_char(s)
    assert left_curly == "{"

    new_line = parse_char(s)
    assert new_line == "\n"

    statements = []

    parse_ws(s)
    statements.append(parse_statement(s))
    parse_ws(s)

    right_curly = parse_char(s)
    assert right_curly == "}"

    return Block(statements)


def parse_function(s: Source):
    fn_indent = parse_indent(s)
    assert fn_indent == "fn"
    parse_ws(s)

    name = parse_indent(s)
    parse_ws(s)
    parse_params(s)
    parse_ws(s)
    block = parse_block(s)

    return Function(name=name, block=block)


def parse(filepath: pathlib.Path):
    source = filepath.read_text()
    f = parse_function(Source(source))
    return f


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=pathlib.Path)
    args = parser.parse_args()

    input_file_path = pathlib.Path(args.file)

    fn = parse(input_file_path)

    output = open("program.s", "w")
    output.write(f'\t.file\t"{input_file_path.name}"\n')
    output.write("\t.text\n")  # code section
    output.write("\t.globl\tmain\n")  # main accessible by linker
    output.write("\t.type\tmain, @function\n")  # main is function, for linker
    output.write("main:\n")  # label where function starts
    # save %rbp value in stack, to restore it in the end
    output.write("\tpushq\t%rbp\n")
    # establish new stack frame for `main`
    output.write("\tmovq\t%rsp, %rbp\n")
    output.write(
        f"\tmovl\t${fn.block.statements[0]}, %eax\n"
    )  # move 42 to return register
    output.write("\tpopq\t%rbp\n")  # restore previous base pointer from stack
    output.write("\tret\n")  # return control to the caller
    # calculate main function size for debugging
    # ".-main" .(current place) -(minus) main(label)
    output.write("\t.size\tmain, .-main\n")
    output.write('\t.ident\t"NONAME"\n')  # compiler metadata
    # no execution stack is needed
    output.write('\t.section\t.note.GNU-stack,"",@progbits\n')
    output.close()


if __name__ == "__main__":
    main()
