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
        self.i8 = ir.IntType(8)
        self.builder: ir.IRBuilder | None = None
        self.function: ir.Function | None = None
        self.allocas: dict[str, ir.AllocaInstr] = {}
        self.var_types: dict[str, ir.Type] = {}
        self.string_id = 0

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
        self.var_types = {}

        entry = fn.append_basic_block("entry")
        self.builder = ir.IRBuilder(entry)

        for arg, param in zip(fn.args, func.params, strict=False):
            arg.name = param.name
            slot = self.builder.alloca(self.i32, name=param.name)
            self.builder.store(arg, slot)
            self.allocas[param.name] = slot
            self.var_types[param.name] = self.i32

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
                slot = self.builder.alloca(value.type, name=stmt.name)
                self.builder.store(self.coerce(value, value.type), slot)
                self.allocas[stmt.name] = slot
                self.var_types[stmt.name] = value.type
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
            if isinstance(expr.value, str):
                return self.compile_string_literal(expr.value)
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
                slot = self.builder.alloca(value.type, name=expr.target.name)
                self.allocas[expr.target.name] = slot
                self.var_types[expr.target.name] = value.type
            self.builder.store(value, slot)
            return value
        if isinstance(expr, Call):
            if isinstance(expr.func, Var):
                callee = self.module.globals.get(expr.func.name)
                if not isinstance(callee, ir.Function):
                    if expr.func.name == "print":
                        callee = None
                    else:
                        raise NotImplementedError(f"unknown function {expr.func.name}")
                args = [self.compile_expr(arg.value) for arg in expr.args]
                if expr.func.name == "print":
                    if len(args) != 1:
                        raise NotImplementedError("print expects exactly one argument")
                    arg = args[0]
                    if isinstance(arg.type, ir.PointerType) and arg.type.pointee == self.i8:
                        callee = self.get_print_str()
                        return self.builder.call(callee, [arg])
                    callee = self.get_print_int()
                    return self.builder.call(callee, [self.coerce_i32(arg)])
                if callee is None:
                    raise NotImplementedError(f"unknown function {expr.func.name}")
                coerced_args = [self.coerce_i32(arg) for arg in args]
                return self.builder.call(callee, coerced_args)
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

    def coerce(self, value: ir.Value, target: ir.Type) -> ir.Value:
        if value.type == target:
            return value
        if target == self.i32:
            return self.coerce_i32(value)
        if target == self.i1:
            return self.coerce_i1(value)
        raise NotImplementedError("unsupported type coercion")

    def compile_string_literal(self, value: str) -> ir.Value:
        encoded = value.encode("utf-8") + b"\x00"
        const_type = ir.ArrayType(self.i8, len(encoded))
        const_val = ir.Constant(const_type, bytearray(encoded))
        name = f".str.{self.string_id}"
        self.string_id += 1
        global_var = ir.GlobalVariable(self.module, const_type, name=name)
        global_var.linkage = "internal"
        global_var.global_constant = True
        global_var.initializer = const_val
        zero = ir.Constant(self.i32, 0)
        return self.builder.gep(global_var, [zero, zero], inbounds=True)

    def get_print_int(self) -> ir.Function:
        callee = self.module.globals.get("print")
        if not isinstance(callee, ir.Function):
            callee = ir.Function(self.module, ir.FunctionType(self.i32, [self.i32]), name="print")
        return callee

    def get_print_str(self) -> ir.Function:
        callee = self.module.globals.get("print_str")
        if not isinstance(callee, ir.Function):
            callee = ir.Function(
                self.module,
                ir.FunctionType(self.i32, [self.i8.as_pointer()]),
                name="print_str",
            )
        return callee


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
