# Vexil

A compiled, general-purpose programming language with Python-like readability and native performance.

```vexil
def fact(n: int) -> int {
    if n <= 1 {
        return 1
    }
    return n * fact(n - 1)
}

def main() {
    let x = fact(5)
    print(x)
}
```

## Features

- **Compiled to native code** via LLVM
- **Tagged enums** with pattern matching
- **Generic types** for enums, classes, and functions
- **Explicit error handling** using `Result` and `Option` types
- **Classes** with inheritance
- **Modules** with file-based imports and exports

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run vexil run examples/hello.vx
```

## Usage

```bash
vexil run <file.vx>       # compile and run
vexil build <file.vx>     # compile to binary
```

## Examples

See the [`examples/`](examples/) directory for more:

- [`hello.vx`](examples/hello.vx) - Hello world
- [`factorial.vx`](examples/factorial.vx) - Recursive factorial
- [`enums_match.vx`](examples/enums_match.vx) - Tagged enums and pattern matching
- [`option_error_handling.vx`](examples/option_error_handling.vx) - Generic `Option<T>` for safe error handling
- [`classes.vx`](examples/classes.vx) - Classes and methods
- [`imports.vx`](examples/imports.vx) - Module imports

## Documentation

- [Language Design](docs/design.md) - Full language specification
- [Grammar (EBNF)](grammar.ebnf) - Formal grammar

## Development

```bash
uv sync --group dev
uv run pytest
```
