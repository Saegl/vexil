from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

from llvmlite import binding, ir

from dataclasses import dataclass

from parser import (
    Assign,
    Binary,
    Block,
    Call,
    CallArg,
    Member,
    ConstructorPattern,
    Expr,
    ExprStmt,
    FuncDef,
    IfStmt,
    LetDecl,
    Literal,
    LiteralPattern,
    MatchExpr,
    NamedType,
    VarPattern,
    Program,
    ReturnStmt,
    Unary,
    Var,
    WildcardPattern,
    EnumDef,
    TypeExpr,
)


class Compiler:
    def __init__(self) -> None:
        self.module = ir.Module(name="vexil")
        self.i32 = ir.IntType(32)
        self.i1 = ir.IntType(1)
        self.i8 = ir.IntType(8)
        self.f64 = ir.DoubleType()
        self.builder: ir.IRBuilder | None = None
        self.function: ir.Function | None = None
        self.allocas: dict[str, ir.AllocaInstr] = {}
        self.var_types: dict[str, ir.Type] = {}
        self.string_id = 0
        self.enum_defs: dict[str, EnumInfo] = {}
        self.enum_types: dict[ir.Type, EnumInfo] = {}
        self.current_return_type: ir.Type | None = None

    def compile_program(self, program: Program) -> ir.Module:
        for stmt in program.statements:
            if isinstance(stmt, EnumDef):
                self.register_enum(stmt)
        for stmt in program.statements:
            if isinstance(stmt, FuncDef):
                self.compile_function(stmt)
        return self.module

    def compile_function(self, func: FuncDef) -> None:
        param_types = [self.type_from_typeexpr(p.type_expr) for p in func.params]
        ret_type = self.type_from_typeexpr(func.return_type)
        fn_type = ir.FunctionType(ret_type, param_types)
        fn = ir.Function(self.module, fn_type, name=func.name)
        self.function = fn
        self.allocas = {}
        self.var_types = {}
        self.current_return_type = ret_type

        entry = fn.append_basic_block("entry")
        self.builder = ir.IRBuilder(entry)

        for arg, param, ptype in zip(fn.args, func.params, param_types, strict=False):
            arg.name = param.name
            slot = self.builder.alloca(ptype, name=param.name)
            self.builder.store(arg, slot)
            self.allocas[param.name] = slot
            self.var_types[param.name] = ptype

        self.compile_block(func.body)

        if not self.builder.block.is_terminated:
            self.builder.ret(self.zero_for_type(ret_type))

        self.function = None
        self.builder = None
        self.allocas = {}
        self.current_return_type = None

    def compile_block(self, block: Block) -> None:
        for stmt in block.statements:
            if self.builder is None or self.builder.block.is_terminated:
                return
            if isinstance(stmt, ReturnStmt):
                if stmt.value is None:
                    if self.current_return_type is None:
                        raise NotImplementedError("unknown return type")
                    self.builder.ret(self.zero_for_type(self.current_return_type))
                else:
                    value = self.compile_expr(stmt.value)
                    assert self.current_return_type is not None
                    self.builder.ret(self.coerce(value, self.current_return_type))
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
            if isinstance(expr.value, float):
                return self.f64(expr.value)
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
                if value.type == self.f64:
                    return self.builder.fneg(value)
                return self.builder.neg(self.coerce_i32(value))
            if expr.op == "+":
                if value.type == self.f64:
                    return value
                return self.coerce_i32(value)
            if expr.op == "!":
                return self.builder.icmp_signed("==", self.coerce_i1(value), self.i1(0))
            raise NotImplementedError(f"unary op {expr.op}")
        if isinstance(expr, Binary):
            left = self.compile_expr(expr.left)
            right = self.compile_expr(expr.right)
            if expr.op == "+":
                if left.type == self.f64 and right.type == self.f64:
                    return self.builder.fadd(left, right)
                return self.builder.add(self.coerce_i32(left), self.coerce_i32(right))
            if expr.op == "-":
                if left.type == self.f64 and right.type == self.f64:
                    return self.builder.fsub(left, right)
                return self.builder.sub(self.coerce_i32(left), self.coerce_i32(right))
            if expr.op == "*":
                if left.type == self.f64 and right.type == self.f64:
                    return self.builder.fmul(left, right)
                return self.builder.mul(self.coerce_i32(left), self.coerce_i32(right))
            if expr.op == "/":
                if left.type == self.f64 and right.type == self.f64:
                    return self.builder.fdiv(left, right)
                return self.builder.sdiv(self.coerce_i32(left), self.coerce_i32(right))
            if expr.op == "%":
                return self.builder.srem(self.coerce_i32(left), self.coerce_i32(right))
            if expr.op in {"<", "<=", ">", ">=", "==", "!="}:
                if left.type == self.f64 and right.type == self.f64:
                    op = {
                        "<": "<",
                        "<=": "<=",
                        ">": ">",
                        ">=": ">=",
                        "==": "==",
                        "!=": "!=",
                    }[expr.op]
                    return self.builder.fcmp_ordered(op, left, right)
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
            value = self.compile_expr(expr.value)
            slot = self.allocas.get(expr.target.name)
            if slot is None:
                slot = self.builder.alloca(value.type, name=expr.target.name)
                self.allocas[expr.target.name] = slot
                self.var_types[expr.target.name] = value.type
            self.builder.store(self.coerce(value, value.type), slot)
            return value
        if isinstance(expr, Call):
            if isinstance(expr.func, Var):
                callee = self.module.globals.get(expr.func.name)
                if not isinstance(callee, ir.Function):
                    if expr.func.name == "print":
                        callee = None
                    elif expr.func.name == "read_line":
                        callee = self.get_read_line()
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
                    if arg.type == self.f64:
                        callee = self.get_print_float()
                        return self.builder.call(callee, [arg])
                    callee = self.get_print_int()
                    return self.builder.call(callee, [self.coerce_i32(arg)])
                if expr.func.name == "read_line":
                    if args:
                        raise NotImplementedError("read_line expects no arguments")
                    return self.builder.call(callee, [])
                if callee is None:
                    raise NotImplementedError(f"unknown function {expr.func.name}")
                param_types = list(callee.function_type.args)
                if len(param_types) != len(args):
                    raise NotImplementedError("argument count mismatch")
                coerced_args = [
                    self.coerce(arg, ptype) for arg, ptype in zip(args, param_types, strict=False)
                ]
                return self.builder.call(callee, coerced_args)
            if isinstance(expr.func, Member):
                if self.is_enum_constructor(expr.func):
                    return self.compile_enum_constructor(expr.func, expr.args)
                return self.compile_method_call(expr.func, expr.args)
            raise NotImplementedError("only direct function calls are supported")
        if isinstance(expr, MatchExpr):
            return self.compile_match(expr)
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
        if target == self.f64 and value.type == self.i32:
            return self.builder.sitofp(value, self.f64)
        if isinstance(target, ir.LiteralStructType) and value.type == target:
            return value
        raise NotImplementedError("unsupported type coercion")

    def zero_for_type(self, typ: ir.Type) -> ir.Constant:
        if typ == self.i32:
            return self.i32(0)
        if typ == self.i1:
            return self.i1(0)
        if typ == self.f64:
            return self.f64(0.0)
        if isinstance(typ, ir.LiteralStructType):
            elements = [self.i32(0) for _ in range(len(typ.elements))]
            return ir.Constant(typ, elements)
        raise NotImplementedError("zero value for type not supported")

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

    def get_print_float(self) -> ir.Function:
        callee = self.module.globals.get("print_float")
        if not isinstance(callee, ir.Function):
            callee = ir.Function(
                self.module,
                ir.FunctionType(self.i32, [self.f64]),
                name="print_float",
            )
        return callee

    def get_read_line(self) -> ir.Function:
        callee = self.module.globals.get("read_line")
        if not isinstance(callee, ir.Function):
            callee = ir.Function(
                self.module,
                ir.FunctionType(self.i8.as_pointer(), []),
                name="read_line",
            )
        return callee

    def get_format1(self) -> ir.Function:
        callee = self.module.globals.get("format1")
        if not isinstance(callee, ir.Function):
            callee = ir.Function(
                self.module,
                ir.FunctionType(self.i8.as_pointer(), [self.i8.as_pointer(), self.i8.as_pointer()]),
                name="format1",
            )
        return callee

    def type_from_typeexpr(self, type_expr: TypeExpr | None) -> ir.Type:
        if type_expr is None:
            return self.i32
        if isinstance(type_expr, NamedType):
            if type_expr.args:
                raise NotImplementedError("generic types are not supported in the backend")
            if type_expr.name == "int":
                return self.i32
            if type_expr.name == "bool":
                return self.i1
            if type_expr.name == "string":
                return self.i8.as_pointer()
            if type_expr.name == "float":
                return self.f64
            enum_info = self.enum_defs.get(type_expr.name)
            if enum_info is not None:
                return enum_info.ir_type
        raise NotImplementedError(f"unsupported type {type_expr}")

    def register_enum(self, enum_def: EnumDef) -> None:
        variants: dict[str, VariantInfo] = {}
        max_arity = 0
        for idx, variant in enumerate(enum_def.variants):
            arity = len(variant.fields)
            for field in variant.fields:
                field_type = self.type_from_typeexpr(field)
                if field_type != self.i32:
                    raise NotImplementedError("enum fields support only int for now")
            variants[variant.name] = VariantInfo(tag=idx, arity=arity)
            if arity > max_arity:
                max_arity = arity

        ir_type = ir.LiteralStructType([self.i32] + [self.i32] * max_arity)
        info = EnumInfo(name=enum_def.name, ir_type=ir_type, variants=variants)
        self.enum_defs[enum_def.name] = info
        self.enum_types[ir_type] = info

    def is_enum_constructor(self, member: "Member") -> bool:
        return isinstance(member.obj, Var) and member.obj.name in self.enum_defs

    def compile_enum_constructor(self, member: "Member", args: list["CallArg"]) -> ir.Value:
        if not isinstance(member.obj, Var):
            raise NotImplementedError("enum constructor must be Enum.Variant")
        enum_info = self.enum_defs.get(member.obj.name)
        if enum_info is None:
            raise NotImplementedError(f"unknown enum {member.obj.name}")
        variant = enum_info.variants.get(member.name)
        if variant is None:
            raise NotImplementedError(f"unknown variant {member.name} for {member.obj.name}")
        if len(args) != variant.arity:
            raise NotImplementedError("enum constructor arity mismatch")

        value = ir.Constant(enum_info.ir_type, ir.Undefined)
        value = self.builder.insert_value(value, self.i32(variant.tag), 0)

        for idx in range(enum_info.max_payload):
            if idx < variant.arity:
                arg_val = self.coerce_i32(self.compile_expr(args[idx].value))
            else:
                arg_val = self.i32(0)
            value = self.builder.insert_value(value, arg_val, idx + 1)

        return value

    def compile_method_call(self, member: "Member", args: list["CallArg"]) -> ir.Value:
        if member.name != "format":
            raise NotImplementedError("only string.format is supported")
        if len(args) != 1:
            raise NotImplementedError("format expects exactly one argument")
        receiver = self.compile_expr(member.obj)
        arg = self.compile_expr(args[0].value)
        if receiver.type != self.i8.as_pointer() or arg.type != self.i8.as_pointer():
            raise NotImplementedError("format supports only string argument")
        callee = self.get_format1()
        return self.builder.call(callee, [receiver, arg])

    def compile_match(self, expr: MatchExpr) -> ir.Value:
        assert self.builder is not None
        subject_val = self.compile_expr(expr.subject)
        enum_info = self.enum_types.get(subject_val.type)
        if enum_info is not None:
            return self.compile_enum_match(subject_val, enum_info, expr)

        subject = self.coerce_i32(subject_val)
        func = self.builder.function
        result_slot = self.builder.alloca(self.i32, name="match.result")
        end_block = func.append_basic_block("match.end")

        current_block = self.builder.block
        has_fallthrough = True

        for index, arm in enumerate(expr.arms):
            arm_block = func.append_basic_block(f"match.arm{index}")
            is_last = index == len(expr.arms) - 1
            pattern = arm.pattern
            self.builder.position_at_end(current_block)

            if isinstance(pattern, WildcardPattern) or isinstance(pattern, VarPattern):
                self.builder.branch(arm_block)
            elif isinstance(pattern, LiteralPattern):
                lit = pattern.value
                if isinstance(lit, bool):
                    lit_val = self.i32(int(lit))
                elif isinstance(lit, int):
                    lit_val = self.i32(lit)
                else:
                    raise NotImplementedError("match literal must be int/bool")
                cond = self.builder.icmp_signed("==", subject, lit_val)
                next_block = func.append_basic_block(f"match.next{index}")
                self.builder.cbranch(cond, arm_block, next_block)
                current_block = next_block
            else:
                raise NotImplementedError("unsupported match pattern")

            self.builder.position_at_end(arm_block)

            saved_allocas = self.allocas.copy()
            saved_types = self.var_types.copy()
            if isinstance(pattern, VarPattern):
                slot = self.builder.alloca(self.i32, name=pattern.name)
                self.builder.store(subject, slot)
                self.allocas[pattern.name] = slot
                self.var_types[pattern.name] = self.i32

            value = self.coerce_i32(self.compile_expr(arm.expr))
            self.builder.store(value, result_slot)
            if not self.builder.block.is_terminated:
                self.builder.branch(end_block)

            self.allocas = saved_allocas
            self.var_types = saved_types

            if isinstance(pattern, WildcardPattern) or isinstance(pattern, VarPattern):
                has_fallthrough = False
                break

        if has_fallthrough:
            raise NotImplementedError("non-exhaustive match expression")

        self.builder.position_at_end(end_block)
        return self.builder.load(result_slot)

    def compile_enum_match(
        self,
        subject: ir.Value,
        enum_info: "EnumInfo",
        expr: MatchExpr,
    ) -> ir.Value:
        assert self.builder is not None
        func = self.builder.function
        tag = self.builder.extract_value(subject, 0)
        result_slot = self.builder.alloca(self.i32, name="match.result")
        end_block = func.append_basic_block("match.end")

        current_block = self.builder.block
        has_fallthrough = True
        matched_variants: set[str] = set()

        for index, arm in enumerate(expr.arms):
            arm_block = func.append_basic_block(f"match.arm{index}")
            pattern = arm.pattern

            self.builder.position_at_end(current_block)

            if isinstance(pattern, WildcardPattern):
                self.builder.branch(arm_block)
            elif isinstance(pattern, ConstructorPattern):
                variant = enum_info.variants.get(pattern.name)
                if variant is None:
                    raise NotImplementedError("unknown enum variant in match")
                if len(pattern.args) != variant.arity:
                    raise NotImplementedError("enum pattern arity mismatch")
                matched_variants.add(pattern.name)
                cond = self.builder.icmp_signed("==", tag, self.i32(variant.tag))
                next_block = func.append_basic_block(f"match.next{index}")
                self.builder.cbranch(cond, arm_block, next_block)
                current_block = next_block
            elif isinstance(pattern, VarPattern):
                variant = enum_info.variants.get(pattern.name)
                if variant is None or variant.arity != 0:
                    raise NotImplementedError("unsupported enum match pattern")
                matched_variants.add(pattern.name)
                cond = self.builder.icmp_signed("==", tag, self.i32(variant.tag))
                next_block = func.append_basic_block(f"match.next{index}")
                self.builder.cbranch(cond, arm_block, next_block)
                current_block = next_block
            else:
                raise NotImplementedError("unsupported enum match pattern")

            self.builder.position_at_end(arm_block)

            saved_allocas = self.allocas.copy()
            saved_types = self.var_types.copy()

            if isinstance(pattern, ConstructorPattern):
                for idx, pat in enumerate(pattern.args):
                    if not isinstance(pat, VarPattern):
                        raise NotImplementedError("only variable patterns are supported for enum fields")
                    field_val = self.builder.extract_value(subject, idx + 1)
                    slot = self.builder.alloca(self.i32, name=pat.name)
                    self.builder.store(field_val, slot)
                    self.allocas[pat.name] = slot
                    self.var_types[pat.name] = self.i32

            value = self.coerce_i32(self.compile_expr(arm.expr))
            self.builder.store(value, result_slot)
            if not self.builder.block.is_terminated:
                self.builder.branch(end_block)

            self.allocas = saved_allocas
            self.var_types = saved_types

            if isinstance(pattern, WildcardPattern):
                has_fallthrough = False
                break

        if has_fallthrough and matched_variants == set(enum_info.variants.keys()):
            self.builder.position_at_end(current_block)
            self.builder.unreachable()
            has_fallthrough = False

        if has_fallthrough:
            raise NotImplementedError("non-exhaustive match expression")

        self.builder.position_at_end(end_block)
        return self.builder.load(result_slot)


@dataclass(frozen=True)
class VariantInfo:
    tag: int
    arity: int


@dataclass(frozen=True)
class EnumInfo:
    name: str
    ir_type: ir.LiteralStructType
    variants: dict[str, VariantInfo]

    @property
    def max_payload(self) -> int:
        return len(self.ir_type.elements) - 1


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
