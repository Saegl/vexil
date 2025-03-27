from dataclasses import dataclass
from typing import Callable


class Source:
    def __init__(self, source: str):
        self.source = source
        self.pos = 0

    def peek(self) -> str:
        return self.source[self.pos]


type Result[T] = Success[T] | Failure[T]


@dataclass
class Success[T]:
    value: T

    def unwrap(self) -> T:
        return self.value

    def is_succ(self) -> bool:
        return True


@dataclass
class Failure[T]:
    message: str

    def unwrap(self) -> T:
        raise Exception(f"Unwrap on Failure: {self.message}")

    def is_succ(self) -> bool:
        return False


class Parser[T]:
    def __init__(self, fn: Callable[[Source], T]):
        self.fn = fn

    def __call__(self, s: Source) -> Result[T]:
        pos = s.pos
        try:
            out = self.fn(s)
            return Success(out)
        except Exception as e:
            s.pos = pos
            return Failure(str(e))


def char(c: str) -> Parser[str]:
    @Parser
    def parser(s: Source) -> str:
        assert s.peek() == c, f"Cannot parse character '{c}', got '{s.peek()}'"
        s.pos += 1
        return c

    return parser


def keyword(key: str) -> Parser[str]:
    @Parser
    def parser(s: Source) -> str:
        got = s.source[s.pos : s.pos + len(key)]
        assert got == key, f"Cannot parse keyword '{key}', got '{got}'"
        s.pos += len(key)
        return key

    return parser


def choice[T](*parsers: Parser[T]) -> Parser[T]:
    if len(parsers) == 0:
        raise Exception("choice must have at least one variant")

    @Parser
    def parser(s: Source) -> T:
        for p in parsers:
            out = p(s)
            if out.is_succ():
                return out.unwrap()

        raise Exception("None of the choices are correct")

    return parser


@Parser
def ws(s: Source) -> int:
    count = 0
    while s.peek() in [" ", "\t"]:
        s.pos += 1
        count += 1
    return count


@Parser
def ws1(s: Source) -> None:
    count = ws(s).unwrap()
    assert count >= 1, "Expected at least one whitespace character"
