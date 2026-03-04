from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

from llvmlite import binding, ir

from parser import (
    Assign,
    Binary,
    Block,
    Call,
    Expr,
    ExprStmt,
    FuncDef,
    IfStmt,
    LetDecl,
    Literal,
    Program,
    ReturnStmt,
    Unary,
    Var,
)


class Compiler:
    def __init__(self) -> None:
        self.module = ir.Module(name="vexil")
        self.i32 = ir.IntType(32)
        self.i1 = ir.IntType(1)
        self.builder: ir.IRBuilder | None = None
        self.function: ir.Function | None = None
        self.allocas: dict[str, ir.AllocaInstr] = {}

    def compile_program(self, program: Program) -> ir.Module:
        for stmt in program.statements:
            if isinstance(stmt, FuncDef):
                self.compile_function(stmt)
        return self.module

    def compile_function(self, func: FuncDef) -> None:
        fn_type = ir.FunctionType(self.i32, [self.i32] * len(func.params))
        fn = ir.Function(self.module, fn_type, name=func.name)
        self.function = fn
        self.allocas = {}

        entry = fn.append_basic_block("entry")
        self.builder = ir.IRBuilder(entry)

        for arg, param in zip(fn.args, func.params, strict=False):
            arg.name = param.name
            slot = self.builder.alloca(self.i32, name=param.name)
            self.builder.store(arg, slot)
            self.allocas[param.name] = slot

        self.compile_block(func.body)

        if not self.builder.block.is_terminated:
            self.builder.ret(self.i32(0))

        self.function = None
        self.builder = None
        self.allocas = {}

    def compile_block(self, block: Block) -> None:
        for stmt in block.statements:
            if self.builder is None or self.builder.block.is_terminated:
                return
            if isinstance(stmt, ReturnStmt):
                value = self.compile_expr(stmt.value) if stmt.value else self.i32(0)
                self.builder.ret(self.coerce_i32(value))
            elif isinstance(stmt, LetDecl):
                value = self.compile_expr(stmt.value)
                slot = self.builder.alloca(self.i32, name=stmt.name)
                self.builder.store(self.coerce_i32(value), slot)
                self.allocas[stmt.name] = slot
            elif isinstance(stmt, IfStmt):
                self.compile_if(stmt)
            elif isinstance(stmt, ExprStmt):
                self.compile_expr(stmt.expr)
            else:
                raise NotImplementedError(f"stmt not supported: {type(stmt).__name__}")

    def compile_if(self, stmt: IfStmt) -> None:
        assert self.builder is not None
        cond_val = self.coerce_i1(self.compile_expr(stmt.condition))
        with self.builder.if_else(cond_val) as (then_block, else_block):
            with then_block:
                self.compile_block(stmt.then_block)
            with else_block:
                if stmt.else_block is not None:
                    self.compile_block(stmt.else_block)

    def compile_expr(self, expr: Expr) -> ir.Value:
        assert self.builder is not None
        if isinstance(expr, Literal):
            if isinstance(expr.value, bool):
                return self.i1(int(expr.value))
            if isinstance(expr.value, int):
                return self.i32(expr.value)
            raise NotImplementedError("only int/bool literals are supported")
        if isinstance(expr, Var):
            slot = self.allocas.get(expr.name)
            if slot is None:
                raise NotImplementedError(f"unknown variable {expr.name}")
            return self.builder.load(slot)
        if isinstance(expr, Unary):
            value = self.compile_expr(expr.expr)
            if expr.op == "-":
                return self.builder.neg(self.coerce_i32(value))
            if expr.op == "+":
                return self.coerce_i32(value)
            if expr.op == "!":
                return self.builder.icmp_signed("==", self.coerce_i1(value), self.i1(0))
            raise NotImplementedError(f"unary op {expr.op}")
        if isinstance(expr, Binary):
            left = self.compile_expr(expr.left)
            right = self.compile_expr(expr.right)
            if expr.op == "+":
                return self.builder.add(self.coerce_i32(left), self.coerce_i32(right))
            if expr.op == "-":
                return self.builder.sub(self.coerce_i32(left), self.coerce_i32(right))
            if expr.op == "*":
                return self.builder.mul(self.coerce_i32(left), self.coerce_i32(right))
            if expr.op == "/":
                return self.builder.sdiv(self.coerce_i32(left), self.coerce_i32(right))
            if expr.op == "%":
                return self.builder.srem(self.coerce_i32(left), self.coerce_i32(right))
            if expr.op in {"<", "<=", ">", ">=", "==", "!="}:
                op = {
                    "<": "<",
                    "<=": "<=",
                    ">": ">",
                    ">=": ">=",
                    "==": "==",
                    "!=": "!=",
                }[expr.op]
                return self.builder.icmp_signed(
                    op, self.coerce_i32(left), self.coerce_i32(right)
                )
            raise NotImplementedError(f"binary op {expr.op}")
        if isinstance(expr, Assign):
            if not isinstance(expr.target, Var):
                raise NotImplementedError("assignment target must be a variable")
            value = self.coerce_i32(self.compile_expr(expr.value))
            slot = self.allocas.get(expr.target.name)
            if slot is None:
                slot = self.builder.alloca(self.i32, name=expr.target.name)
                self.allocas[expr.target.name] = slot
            self.builder.store(value, slot)
            return value
        if isinstance(expr, Call):
            if isinstance(expr.func, Var):
                callee = self.module.globals.get(expr.func.name)
                if not isinstance(callee, ir.Function):
                    if expr.func.name == "print":
                        callee = ir.Function(
                            self.module,
                            ir.FunctionType(self.i32, [self.i32]),
                            name="print",
                        )
                    else:
                        raise NotImplementedError(f"unknown function {expr.func.name}")
                args = [
                    self.coerce_i32(self.compile_expr(arg.value)) for arg in expr.args
                ]
                return self.builder.call(callee, args)
            raise NotImplementedError("only direct function calls are supported")
        raise NotImplementedError(f"expr not supported: {type(expr).__name__}")

    def coerce_i32(self, value: ir.Value) -> ir.Value:
        if value.type == self.i32:
            return value
        if value.type == self.i1:
            return self.builder.zext(value, self.i32)
        raise NotImplementedError("unsupported type coercion to i32")

    def coerce_i1(self, value: ir.Value) -> ir.Value:
        if value.type == self.i1:
            return value
        if value.type == self.i32:
            return self.builder.icmp_signed("!=", value, self.i32(0))
        raise NotImplementedError("unsupported type coercion to i1")


def emit_object(module: ir.Module) -> bytes:
    binding.initialize_native_target()
    binding.initialize_native_asmprinter()

    llvm_module = binding.parse_assembly(str(module))
    llvm_module.verify()

    target = binding.Target.from_default_triple()
    target_machine = target.create_target_machine()
    return target_machine.emit_object(llvm_module)


def build_executable(module: ir.Module, output_path: Path) -> None:
    obj_bytes = emit_object(module)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        obj_path = tmpdir_path / "vexil.o"
        runtime_obj = tmpdir_path / "runtime.o"

        obj_path.write_bytes(obj_bytes)

        compiler = shutil.which("clang") or shutil.which("gcc") or shutil.which("cc")
        if compiler is None:
            raise RuntimeError("No C compiler found (expected clang, gcc, or cc).")

        subprocess.run(
            [compiler, "-c", "runtime.c", "-o", str(runtime_obj), "-fno-pie"],
            check=True,
            cwd=Path(__file__).resolve().parent,
        )
        subprocess.run(
            [compiler, str(obj_path), str(runtime_obj), "-o", str(output_path), "-no-pie"],
            check=True,
        )
