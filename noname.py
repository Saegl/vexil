import argparse
import pathlib


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=pathlib.Path)
    args = parser.parse_args()

    input_file_path = pathlib.Path(args.file)
    retval = 13

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
    output.write(f"\tmovl\t${retval}, %eax\n")  # move 42 to return register
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
