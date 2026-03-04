from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Generator, Optional, cast

import parsy


# === AST ===

Parser = parsy.Parser[Any]


@dataclass(frozen=True)
class Program:
    statements: list["Stmt"]


class Stmt:
    pass


@dataclass(frozen=True)
class Block(Stmt):
    statements: list[Stmt]


@dataclass(frozen=True)
class ImportStmt(Stmt):
    path: str


@dataclass(frozen=True)
class FromImportStmt(Stmt):
    path: str
    names: list[str]


@dataclass(frozen=True)
class LetDecl(Stmt):
    name: str
    type_expr: Optional["TypeExpr"]
    value: "Expr"
    is_const: bool
    is_export: bool


@dataclass(frozen=True)
class FuncDef(Stmt):
    name: str
    type_params: list["TypeParam"]
    params: list["Param"]
    return_type: Optional["TypeExpr"]
    body: Block
    is_export: bool


@dataclass(frozen=True)
class ClassDef(Stmt):
    name: str
    type_params: list["TypeParam"]
    base: Optional["TypeExpr"]
    fields: list["FieldDecl"]
    methods: list[FuncDef]
    is_export: bool


@dataclass(frozen=True)
class FieldDecl:
    name: str
    type_expr: "TypeExpr"


@dataclass(frozen=True)
class EnumDef(Stmt):
    name: str
    type_params: list["TypeParam"]
    variants: list["EnumVariant"]
    is_export: bool


@dataclass(frozen=True)
class EnumVariant:
    name: str
    fields: list["TypeExpr"]


@dataclass(frozen=True)
class ReturnStmt(Stmt):
    value: Optional["Expr"]


@dataclass(frozen=True)
class IfStmt(Stmt):
    condition: "Expr"
    then_block: Block
    else_block: Optional[Block]


@dataclass(frozen=True)
class ExprStmt(Stmt):
    expr: "Expr"


@dataclass(frozen=True)
class Param:
    name: str
    type_expr: Optional["TypeExpr"]
    default: Optional["Expr"]


@dataclass(frozen=True)
class TypeParam:
    name: str
    bound: Optional["TypeExpr"]


class TypeExpr:
    pass


@dataclass(frozen=True)
class NamedType(TypeExpr):
    name: str
    args: list["TypeExpr"]


class Expr:
    pass


@dataclass(frozen=True)
class Var(Expr):
    name: str


@dataclass(frozen=True)
class Literal(Expr):
    value: Any


@dataclass(frozen=True)
class Unary(Expr):
    op: str
    expr: Expr


@dataclass(frozen=True)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Assign(Expr):
    target: Expr
    value: Expr


@dataclass(frozen=True)
class Member(Expr):
    obj: Expr
    name: str


@dataclass(frozen=True)
class CallArg:
    name: Optional[str]
    value: Expr


@dataclass(frozen=True)
class Call(Expr):
    func: Expr
    args: list[CallArg]


@dataclass(frozen=True)
class MatchExpr(Expr):
    subject: Expr
    arms: list["MatchArm"]


@dataclass(frozen=True)
class MatchArm:
    pattern: "Pattern"
    expr: Expr


class Pattern:
    pass


@dataclass(frozen=True)
class WildcardPattern(Pattern):
    pass


@dataclass(frozen=True)
class VarPattern(Pattern):
    name: str


@dataclass(frozen=True)
class ConstructorPattern(Pattern):
    name: str
    args: list[Pattern]


@dataclass(frozen=True)
class LiteralPattern(Pattern):
    value: Any


# === Lexer helpers ===


keywords = {
    "let",
    "const",
    "def",
    "class",
    "enum",
    "return",
    "if",
    "else",
    "match",
    "import",
    "from",
    "export",
    "true",
    "false",
}


inline_ws = parsy.regex(r"[ \t]+")
comment = parsy.regex(r"#.*")
line_ws = (inline_ws | comment).many()
newline = parsy.regex(r"\n+")
semi = parsy.string(";")


def lexeme(p: Parser) -> Parser:
    return line_ws >> p << line_ws


def kw(text: str) -> Parser:
    pattern = rf"{re.escape(text)}(?![A-Za-z0-9_])"
    return lexeme(parsy.regex(pattern)).result(text)


ident_raw = parsy.regex(r"[A-Za-z_][A-Za-z0-9_]*")
ident = lexeme(ident_raw).bind(
    lambda s: parsy.fail("keyword") if s in keywords else parsy.success(s)
)

integer = lexeme(parsy.regex(r"[0-9]+").map(int))
floating = lexeme(
    parsy.regex(r"[0-9]+\.[0-9]+").map(float)
)


@parsy.generate
def string_lit() -> Generator[Parser, Any, Any]:
    yield line_ws
    yield parsy.string('"')
    body = yield parsy.regex(r'([^"\\]|\\.)*')
    yield parsy.string('"')
    yield line_ws
    return bytes(body, "utf-8").decode("unicode_escape")


literal = (
    floating.map(Literal)
    | integer.map(Literal)
    | string_lit.map(Literal)
    | kw("true").result(Literal(True))
    | kw("false").result(Literal(False))
)


stmt_sep = (line_ws >> (semi | newline)).at_least(1).map(lambda _: None)


def parens(p: Parser) -> Parser:
    return lexeme(parsy.string("(")) >> p << lexeme(parsy.string(")"))


def braces(p: Parser) -> Parser:
    return lexeme(parsy.string("{")) >> p << lexeme(parsy.string("}"))


def comma_sep(p: Parser) -> Parser:
    return p.sep_by(lexeme(parsy.string(",")))


# === Forward declarations ===


type_expr: Parser = parsy.forward_declaration()
expr: Parser = parsy.forward_declaration()
stmt: Parser = parsy.forward_declaration()


# === Types ===


@parsy.generate
def type_param() -> Generator[Parser, Any, TypeParam]:
    name = yield ident
    bound = yield (lexeme(parsy.string(":")) >> type_expr).optional()
    return TypeParam(name, bound)


type_params = (
    lexeme(parsy.string("<"))
    >> comma_sep(type_param)
    << lexeme(parsy.string(">"))
)


@parsy.generate
def named_type() -> Generator[Parser, Any, TypeExpr]:
    name = yield ident
    args = yield (
        lexeme(parsy.string("<")) >> comma_sep(type_expr) << lexeme(parsy.string(">"))
    ).optional(default=[])
    return NamedType(name, args)


type_expr.become(named_type)


# === Expressions ===


@parsy.generate
def match_expr() -> Generator[Parser, Any, Expr]:
    yield kw("match")
    subject = yield expr
    arms = yield braces(
        stmt_sep.optional()
        >> match_arm.sep_by(stmt_sep)
        << stmt_sep.optional()
    )
    return MatchExpr(subject, arms)


@parsy.generate
def pattern() -> Generator[Parser, Any, Pattern]:
    wildcard = yield kw("_").optional()
    if wildcard is not None:
        return WildcardPattern()
    lit = yield literal.optional()
    if lit is not None:
        return LiteralPattern(lit.value)
    name = yield ident
    args = yield parens(
        comma_sep(pattern)
    ).optional(default=[])
    if args:
        return ConstructorPattern(name, args)
    return VarPattern(name)


@parsy.generate
def match_arm() -> Generator[Parser, Any, MatchArm]:
    pat = yield pattern
    yield lexeme(parsy.string("=>"))
    value = yield expr
    return MatchArm(pat, value)


@parsy.generate
def primary_expr() -> Generator[Parser, Any, Expr]:
    if_expr = yield match_expr.optional()
    if if_expr is not None:
        return cast(Expr, if_expr)
    lit = yield literal.optional()
    if lit is not None:
        return cast(Expr, lit)
    name = yield ident.optional()
    if name is not None:
        return Var(name)
    grouped = yield parens(expr)
    return cast(Expr, grouped)


@parsy.generate
def call_expr() -> Generator[Parser, Any, Expr]:
    value = yield primary_expr
    while True:
        member = yield (lexeme(parsy.string(".")) >> ident).optional()
        if member is not None:
            value = Member(value, member)
            continue
        args = yield parens(
            comma_sep(arg)
        ).optional()
        if args is not None:
            value = Call(value, args)
            continue
        break
    return cast(Expr, value)


@parsy.generate
def arg() -> Generator[Parser, Any, CallArg]:
    name = yield (ident << lexeme(parsy.string("="))).optional()
    if name is not None:
        value = yield expr
        return CallArg(name, value)
    value = yield expr
    return CallArg(None, value)


def infix_left(operand: Parser, ops: Parser) -> Parser:
    @parsy.generate
    def parser() -> Generator[Parser, Any, Expr]:
        left = yield operand
        while True:
            op = yield ops.optional()
            if op is None:
                break
            right = yield operand
            left = Binary(op, left, right)
        return cast(Expr, left)

    return parser


unary_ops = lexeme(parsy.string("!")) | lexeme(parsy.string("+")) | lexeme(
    parsy.string("-")
)


@parsy.generate
def unary_expr() -> Generator[Parser, Any, Expr]:
    op = yield unary_ops.optional()
    if op is not None:
        value = yield unary_expr
        return Unary(op, value)
    return cast(Expr, (yield call_expr))


mul_expr = infix_left(
    unary_expr, lexeme(parsy.string("*")) | lexeme(parsy.string("/")) | lexeme(parsy.string("%"))
)
add_expr = infix_left(
    mul_expr, lexeme(parsy.string("+")) | lexeme(parsy.string("-"))
)
compare_expr = infix_left(
    add_expr,
    lexeme(parsy.string("<="))
    | lexeme(parsy.string(">="))
    | lexeme(parsy.string("<"))
    | lexeme(parsy.string(">")),
)
equality_expr = infix_left(
    compare_expr, lexeme(parsy.string("==")) | lexeme(parsy.string("!="))
)
and_expr = infix_left(equality_expr, lexeme(parsy.string("&&")))
or_expr = infix_left(and_expr, lexeme(parsy.string("||")))


@parsy.generate
def assign_expr() -> Generator[Parser, Any, Expr]:
    left = yield or_expr
    if (yield lexeme(parsy.string("=")).optional()) is None:
        return cast(Expr, left)
    right = yield assign_expr
    return Assign(left, right)


expr.become(assign_expr)


# === Statements ===


@parsy.generate
def block() -> Generator[Parser, Any, Block]:
    stmts = yield braces(stmt_sep.optional() >> stmt.sep_by(stmt_sep) << stmt_sep.optional())
    return Block(stmts)


def let_decl(is_const: bool, is_export: bool) -> Parser:
    @parsy.generate
    def parser() -> Generator[Parser, Any, LetDecl]:
        yield kw("const" if is_const else "let")
        name = yield ident
        type_annotation = yield (lexeme(parsy.string(":")) >> type_expr).optional()
        yield lexeme(parsy.string("="))
        value = yield expr
        return LetDecl(name, type_annotation, value, is_const, is_export)

    return parser


@parsy.generate
def param() -> Generator[Parser, Any, Param]:
    name = yield ident
    type_annotation = yield (lexeme(parsy.string(":")) >> type_expr).optional()
    default = yield (lexeme(parsy.string("=")) >> expr).optional()
    return Param(name, type_annotation, default)


def func_def(is_export: bool) -> Parser:
    @parsy.generate
    def parser() -> Generator[Parser, Any, FuncDef]:
        yield kw("def")
        name = yield ident
        tparams = yield type_params.optional(default=[])
        params = yield parens(comma_sep(param))
        ret = yield (lexeme(parsy.string("->")) >> type_expr).optional()
        body = yield block
        return FuncDef(name, tparams, params, ret, body, is_export)

    return parser


@parsy.generate
def field_decl() -> Generator[Parser, Any, FieldDecl]:
    name = yield ident
    yield lexeme(parsy.string(":"))
    texpr = yield type_expr
    return FieldDecl(name, texpr)


def class_def(is_export: bool) -> Parser:
    @parsy.generate
    def parser() -> Generator[Parser, Any, ClassDef]:
        yield kw("class")
        name = yield ident
        tparams = yield type_params.optional(default=[])
        base = yield parens(type_expr).optional()
        members = yield braces(
            stmt_sep.optional()
            >> class_member.sep_by(stmt_sep)
            << stmt_sep.optional()
        )
        fields: list[FieldDecl] = []
        methods: list[FuncDef] = []
        for m in members:
            if isinstance(m, FieldDecl):
                fields.append(m)
            else:
                methods.append(m)
        return ClassDef(name, tparams, base, fields, methods, is_export)

    return parser


@parsy.generate
def enum_variant() -> Generator[Parser, Any, EnumVariant]:
    name = yield ident
    fields = yield parens(comma_sep(type_expr)).optional(default=[])
    return EnumVariant(name, fields)


def enum_def(is_export: bool) -> Parser:
    @parsy.generate
    def parser() -> Generator[Parser, Any, EnumDef]:
        yield kw("enum")
        name = yield ident
        tparams = yield type_params.optional(default=[])
        variants = yield braces(
            stmt_sep.optional()
            >> enum_variant.sep_by(stmt_sep)
            << stmt_sep.optional()
        )
        return EnumDef(name, tparams, variants, is_export)

    return parser


@parsy.generate
def return_stmt() -> Generator[Parser, Any, ReturnStmt]:
    yield kw("return")
    value = yield expr.optional()
    return ReturnStmt(value)


@parsy.generate
def if_stmt() -> Generator[Parser, Any, IfStmt]:
    yield kw("if")
    cond = yield expr
    then_block = yield block
    else_block = yield (kw("else") >> block).optional()
    return IfStmt(cond, then_block, else_block)


@parsy.generate
def import_stmt() -> Generator[Parser, Any, ImportStmt]:
    yield kw("import")
    path = yield string_lit
    return ImportStmt(path)


@parsy.generate
def from_import_stmt() -> Generator[Parser, Any, FromImportStmt]:
    yield kw("from")
    path = yield string_lit
    yield kw("import")
    names = yield comma_sep(ident)
    return FromImportStmt(path, names)


@parsy.generate
def expr_stmt() -> Generator[Parser, Any, ExprStmt]:
    value = yield expr
    return ExprStmt(value)


@parsy.generate
def export_stmt() -> Generator[Parser, Any, Stmt]:
    yield kw("export")
    exportable = yield (
        func_def(True)
        | class_def(True)
        | enum_def(True)
        | let_decl(False, True)
        | let_decl(True, True)
    )
    return cast(Stmt, exportable)


class_member = (field_decl | func_def(False))

stmt.become(
    export_stmt
    | import_stmt
    | from_import_stmt
    | func_def(False)
    | class_def(False)
    | enum_def(False)
    | let_decl(False, False)
    | let_decl(True, False)
    | return_stmt
    | if_stmt
    | expr_stmt
)


program = (
    line_ws
    >> stmt_sep.optional()
    >> stmt.sep_by(stmt_sep)
    << stmt_sep.optional()
    << parsy.eof
).map(Program)


def parse_program(text: str) -> Program:
    return cast(Program, program.parse(text))
