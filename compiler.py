from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from llvmlite import binding, ir

from parser import (
    Assign,
    Binary,
    Block,
    Call,
    CallArg,
    ClassDef,
    ConstructorPattern,
    EnumDef,
    EnumVariant,
    Expr,
    ExprStmt,
    FieldDecl,
    FuncDef,
    IfStmt,
    LetDecl,
    Literal,
    LiteralPattern,
    MatchExpr,
    Member,
    NamedType,
    Program,
    ReturnStmt,
    TypeExpr,
    Unary,
    Var,
    VarPattern,
    WildcardPattern,
)


class Compiler:
    def __init__(self) -> None:
        binding.initialize_native_target()
        binding.initialize_native_asmprinter()
        target = binding.Target.from_default_triple()
        self.target_machine = target.create_target_machine()
        self.target_data = self.target_machine.target_data

        self.module = ir.Module(name="vexil")
        self.i32 = ir.IntType(32)
        self.i1 = ir.IntType(1)
        self.i64 = ir.IntType(64)
        self.i8 = ir.IntType(8)
        self.f64 = ir.DoubleType()
        self.builder: ir.IRBuilder | None = None
        self.function: ir.Function | None = None
        self.allocas: dict[str, ir.AllocaInstr] = {}
        self.var_types: dict[str, ir.Type] = {}
        self.string_id = 0
        self.enum_defs: dict[str, EnumInfo] = {}
        self.enum_types: dict[ir.Type, EnumInfo] = {}
        self.enum_defs_by_key: dict[tuple[str, tuple[ir.Type, ...]], EnumInfo] = {}
        self.enum_ast_defs: dict[str, EnumDef] = {}
        self.current_return_type: ir.Type | None = None
        self.class_defs: dict[str, ClassInfo] = {}
        self.class_types: dict[ir.Type, ClassInfo] = {}

    def compile_program(self, program: Program) -> ir.Module:
        for stmt in program.statements:
            if isinstance(stmt, EnumDef):
                self.register_enum(stmt)
            if isinstance(stmt, ClassDef):
                self.register_class(stmt)
        for stmt in program.statements:
            if isinstance(stmt, FuncDef):
                self.compile_function(stmt)
            if isinstance(stmt, ClassDef):
                self.compile_class_methods(stmt)
        return self.module

    def compile_function(
        self,
        func: FuncDef,
        *,
        method_of: ClassInfo | None = None,
    ) -> None:
        param_types = [self.type_from_typeexpr(p.type_expr) for p in func.params]
        ret_type = self.type_from_typeexpr(func.return_type)
        if method_of is not None:
            if not func.params or func.params[0].name != "self":
                raise NotImplementedError("methods must take self as first parameter")
            param_types[0] = method_of.ptr_type
        fn_type = ir.FunctionType(ret_type, param_types)
        fn_name = func.name if method_of is None else f"{method_of.name}__{func.name}"
        fn = ir.Function(self.module, fn_type, name=fn_name)
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
                    value = self.compile_expr_with_expected(
                        stmt.value, self.current_return_type
                    )
                    assert self.current_return_type is not None
                    self.builder.ret(self.coerce(value, self.current_return_type))
            elif isinstance(stmt, LetDecl):
                expected_type = (
                    self.type_from_typeexpr(stmt.type_expr)
                    if stmt.type_expr is not None
                    else None
                )
                value = self.compile_expr_with_expected(stmt.value, expected_type)
                slot_type = expected_type or value.type
                slot = self.builder.alloca(slot_type, name=stmt.name)
                self.builder.store(self.coerce(value, slot_type), slot)
                self.allocas[stmt.name] = slot
                self.var_types[stmt.name] = slot_type
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
        return self.compile_expr_with_expected(expr, None)

    def compile_expr_with_expected(
        self, expr: Expr, expected_type: ir.Type | None
    ) -> ir.Value:
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
        if isinstance(expr, Member):
            return self.compile_member_load(expr)
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
            target_type = None
            if isinstance(expr.target, Var):
                target_type = self.var_types.get(expr.target.name)
            value = self.compile_expr_with_expected(expr.value, target_type)
            if isinstance(expr.target, Var):
                slot = self.allocas.get(expr.target.name)
                if slot is None:
                    slot = self.builder.alloca(value.type, name=expr.target.name)
                    self.allocas[expr.target.name] = slot
                    self.var_types[expr.target.name] = value.type
                store_type = self.var_types.get(expr.target.name, value.type)
                self.builder.store(self.coerce(value, store_type), slot)
                return value
            if isinstance(expr.target, Member):
                self.compile_member_store(expr.target, value)
                return value
            raise NotImplementedError("assignment target must be a variable or field")
        if isinstance(expr, Call):
            if isinstance(expr.func, Var):
                callee = self.module.globals.get(expr.func.name)
                if not isinstance(callee, ir.Function):
                    if expr.func.name == "print":
                        callee = None
                    elif expr.func.name == "read_line":
                        callee = self.get_read_line()
                    elif expr.func.name in self.class_defs:
                        return self.compile_class_constructor(expr.func.name, expr.args)
                    else:
                        raise NotImplementedError(f"unknown function {expr.func.name}")
                args = [self.compile_expr(arg.value) for arg in expr.args]
                if expr.func.name == "print":
                    if len(args) != 1:
                        raise NotImplementedError("print expects exactly one argument")
                    arg = args[0]
                    if (
                        isinstance(arg.type, ir.PointerType)
                        and arg.type.pointee == self.i8
                    ):
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
                    self.coerce(arg, ptype)
                    for arg, ptype in zip(args, param_types, strict=False)
                ]
                return self.builder.call(callee, coerced_args)
            if isinstance(expr.func, Member):
                if self.is_enum_constructor(expr.func):
                    return self.compile_enum_constructor(
                        expr.func, expr.args, expected_type
                    )
                return self.compile_method_call(expr.func, expr.args)
            raise NotImplementedError("only direct function calls are supported")
        if isinstance(expr, MatchExpr):
            return self.compile_match(expr)
        raise NotImplementedError(f"expr not supported: {type(expr).__name__}")

    def coerce_i32(self, value: ir.Value) -> ir.Value:
        assert self.builder is not None
        if value.type == self.i32:
            return value
        if value.type == self.i1:
            return self.builder.zext(value, self.i32)
        raise NotImplementedError("unsupported type coercion to i32")

    def coerce_i1(self, value: ir.Value) -> ir.Value:
        assert self.builder is not None
        if value.type == self.i1:
            return value
        if value.type == self.i32:
            return self.builder.icmp_signed("!=", value, self.i32(0))
        raise NotImplementedError("unsupported type coercion to i1")

    def coerce(self, value: ir.Value, target: ir.Type) -> ir.Value:
        assert self.builder is not None
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
        if typ == self.i64:
            return self.i64(0)
        if typ == self.f64:
            return self.f64(0.0)
        if isinstance(typ, ir.LiteralStructType):
            elements = [self.zero_for_type(elem) for elem in typ.elements]
            return ir.Constant(typ, elements)
        if isinstance(typ, ir.PointerType):
            return ir.Constant(typ, None)
        raise NotImplementedError("zero value for type not supported")

    def is_supported_enum_field_type(self, typ: ir.Type) -> bool:
        return typ in {self.i32, self.i1, self.f64} or isinstance(
            typ, ir.PointerType
        )

    def pack_enum_payload(self, value: ir.Value) -> ir.Value:
        assert self.builder is not None
        if value.type == self.i32:
            return self.builder.zext(value, self.i64)
        if value.type == self.i1:
            return self.builder.zext(value, self.i64)
        if value.type == self.f64:
            return self.builder.bitcast(value, self.i64)
        if isinstance(value.type, ir.PointerType):
            return self.builder.ptrtoint(value, self.i64)
        raise NotImplementedError("unsupported enum payload type")

    def unpack_enum_payload(self, value: ir.Value, target: ir.Type) -> ir.Value:
        assert self.builder is not None
        if target == self.i32:
            return self.builder.trunc(value, self.i32)
        if target == self.i1:
            return self.builder.trunc(value, self.i1)
        if target == self.f64:
            return self.builder.bitcast(value, self.f64)
        if isinstance(target, ir.PointerType):
            return self.builder.inttoptr(value, target)
        raise NotImplementedError("unsupported enum payload type")

    def compile_string_literal(self, value: str) -> ir.Value:
        assert self.builder is not None
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
            callee = ir.Function(
                self.module,
                ir.FunctionType(self.i32, [self.i32]),
                name="print",
            )
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
                ir.FunctionType(
                    self.i8.as_pointer(),
                    [self.i8.as_pointer(), self.i8.as_pointer()],
                ),
                name="format1",
            )
        return callee

    def type_from_typeexpr(
        self,
        type_expr: TypeExpr | None,
        type_params: dict[str, ir.Type] | None = None,
    ) -> ir.Type:
        if type_expr is None:
            return self.i32
        if isinstance(type_expr, NamedType):
            if (
                type_params is not None
                and not type_expr.args
                and type_expr.name in type_params
            ):
                return type_params[type_expr.name]
            if type_expr.name == "int":
                return self.i32
            if type_expr.name == "bool":
                return self.i1
            if type_expr.name == "string":
                return self.i8.as_pointer()
            if type_expr.name == "float":
                return self.f64
            if type_expr.args:
                arg_types = [
                    self.type_from_typeexpr(arg, type_params) for arg in type_expr.args
                ]
                if type_expr.name in self.enum_ast_defs:
                    enum_info = self.get_enum_info(type_expr.name, arg_types)
                    return enum_info.ir_type
                raise NotImplementedError(
                    "generic types are not supported in the backend"
                )
            if type_expr.name in self.enum_ast_defs:
                enum_info = self.get_enum_info(type_expr.name, None)
                return enum_info.ir_type
            class_info = self.class_defs.get(type_expr.name)
            if class_info is not None:
                return class_info.ptr_type
        raise NotImplementedError(f"unsupported type {type_expr}")

    def register_enum(self, enum_def: EnumDef) -> None:
        self.enum_ast_defs[enum_def.name] = enum_def
        if enum_def.type_params:
            return
        info = self.instantiate_enum(enum_def, {})
        self.enum_defs[enum_def.name] = info
        self.enum_types[info.ir_type] = info

    def instantiate_enum(
        self, enum_def: EnumDef, type_params: dict[str, ir.Type]
    ) -> EnumInfo:
        variants: dict[str, VariantInfo] = {}
        max_arity = 0
        for idx, variant in enumerate(enum_def.variants):
            field_types: list[ir.Type] = []
            for field in variant.fields:
                field_type = self.type_from_typeexpr(field, type_params)
                if not self.is_supported_enum_field_type(field_type):
                    raise NotImplementedError(
                        "enum fields support only int/bool/float/string/class pointers"
                    )
                field_types.append(field_type)
            variants[variant.name] = VariantInfo(tag=idx, fields=field_types)
            if len(field_types) > max_arity:
                max_arity = len(field_types)

        ir_type = ir.LiteralStructType([self.i32] + [self.i64] * max_arity)
        return EnumInfo(name=enum_def.name, ir_type=ir_type, variants=variants)

    def get_enum_info(
        self, name: str, arg_types: list[ir.Type] | None
    ) -> EnumInfo:
        enum_def = self.enum_ast_defs.get(name)
        if enum_def is None:
            raise NotImplementedError(f"unknown enum {name}")
        if not enum_def.type_params:
            if arg_types is not None:
                raise NotImplementedError(
                    "type arguments are not supported for non-generic enums"
                )
            info = self.enum_defs.get(name)
            if info is None:
                info = self.instantiate_enum(enum_def, {})
                self.enum_defs[name] = info
                self.enum_types[info.ir_type] = info
            return info
        if arg_types is None:
            info = self.enum_defs.get(name)
            if info is not None:
                return info
            raise NotImplementedError("generic enum requires type arguments")
        if len(arg_types) != len(enum_def.type_params):
            raise NotImplementedError("generic enum type argument count mismatch")
        key = (name, tuple(arg_types))
        info = self.enum_defs_by_key.get(key)
        if info is not None:
            return info
        type_params = {
            param.name: arg
            for param, arg in zip(enum_def.type_params, arg_types, strict=False)
        }
        info = self.instantiate_enum(enum_def, type_params)
        self.enum_defs_by_key[key] = info
        self.enum_defs.setdefault(name, info)
        self.enum_types[info.ir_type] = info
        return info

    def get_enum_info_for_constructor(
        self,
        enum_def: EnumDef,
        variant_def: EnumVariant,
        arg_values: list[ir.Value],
        expected_type: ir.Type | None,
    ) -> EnumInfo:
        if expected_type is not None:
            expected_enum = self.enum_types.get(expected_type)
            if expected_enum is not None:
                return expected_enum
        if not enum_def.type_params:
            return self.get_enum_info(enum_def.name, None)
        param_names = {param.name for param in enum_def.type_params}
        inferred: dict[str, ir.Type] = {}
        for field, arg in zip(variant_def.fields, arg_values, strict=False):
            if (
                isinstance(field, NamedType)
                and not field.args
                and field.name in param_names
            ):
                inferred[field.name] = arg.type
        if len(inferred) != len(enum_def.type_params):
            raise NotImplementedError(
                "cannot infer generic enum type; add a type annotation"
            )
        arg_types = [inferred[param.name] for param in enum_def.type_params]
        return self.get_enum_info(enum_def.name, arg_types)

    def register_class(self, class_def: ClassDef) -> None:
        fields: list[FieldInfo] = []
        for field in class_def.fields:
            if not isinstance(field, FieldDecl):
                continue
            field_type = self.type_from_typeexpr(field.type_expr)
            if field_type != self.i32:
                raise NotImplementedError("class fields support only int for now")
            fields.append(FieldInfo(name=field.name, ir_type=field_type))

        struct_type = ir.LiteralStructType([f.ir_type for f in fields])
        info = ClassInfo(
            name=class_def.name,
            struct_type=struct_type,
            fields=fields,
        )
        self.class_defs[class_def.name] = info
        self.class_types[info.ptr_type] = info

    def compile_class_methods(self, class_def: ClassDef) -> None:
        info = self.class_defs[class_def.name]
        for method in class_def.methods:
            self.compile_function(method, method_of=info)

    def is_enum_constructor(self, member: Member) -> bool:
        return isinstance(member.obj, Var) and member.obj.name in self.enum_ast_defs

    def compile_enum_constructor(
        self,
        member: Member,
        args: list[CallArg],
        expected_type: ir.Type | None,
    ) -> ir.Value:
        if not isinstance(member.obj, Var):
            raise NotImplementedError("enum constructor must be Enum.Variant")
        enum_def = self.enum_ast_defs.get(member.obj.name)
        if enum_def is None:
            raise NotImplementedError(f"unknown enum {member.obj.name}")
        assert self.builder is not None
        variant_def = next(
            (variant for variant in enum_def.variants if variant.name == member.name),
            None,
        )
        if variant_def is None:
            raise NotImplementedError(
                f"unknown variant {member.name} for {member.obj.name}"
            )
        if len(args) != len(variant_def.fields):
            raise NotImplementedError("enum constructor arity mismatch")

        arg_values = [self.compile_expr(arg.value) for arg in args]
        enum_info = self.get_enum_info_for_constructor(
            enum_def,
            variant_def,
            arg_values,
            expected_type,
        )
        variant = enum_info.variants[variant_def.name]

        value = ir.Constant(enum_info.ir_type, ir.Undefined)
        value = self.builder.insert_value(value, self.i32(variant.tag), 0)

        for idx in range(enum_info.max_payload):
            if idx < variant.arity:
                field_type = variant.fields[idx]
                coerced = self.coerce(arg_values[idx], field_type)
                arg_val = self.pack_enum_payload(coerced)
            else:
                arg_val = self.i64(0)
            value = self.builder.insert_value(value, arg_val, idx + 1)

        return value

    def compile_class_constructor(
        self,
        class_name: str,
        args: list[CallArg],
    ) -> ir.Value:
        class_info = self.class_defs.get(class_name)
        if class_info is None:
            raise NotImplementedError(f"unknown class {class_name}")
        if self.builder is None:
            raise NotImplementedError("no builder available for constructor")

        null_ptr = ir.Constant(class_info.ptr_type, None)
        size_ptr = self.builder.gep(null_ptr, [self.i32(1)], inbounds=True)
        size = self.builder.ptrtoint(size_ptr, self.i32)
        raw_ptr = self.builder.call(self.get_alloc(), [size])
        obj_ptr = self.builder.bitcast(raw_ptr, class_info.ptr_type)

        init_fn = self.module.globals.get(f"{class_name}__init")
        if isinstance(init_fn, ir.Function):
            init_args = [obj_ptr] + [self.compile_expr(arg.value) for arg in args]
            param_types = list(init_fn.function_type.args)
            if len(param_types) != len(init_args):
                raise NotImplementedError("constructor argument count mismatch")
            coerced_args = [
                self.coerce(arg, ptype)
                for arg, ptype in zip(init_args, param_types, strict=False)
            ]
            self.builder.call(init_fn, coerced_args)
        elif args:
            raise NotImplementedError(
                "constructor args provided but no init method defined"
            )

        return obj_ptr

    def compile_member_load(self, member: Member) -> ir.Value:
        assert self.builder is not None
        obj = self.compile_expr(member.obj)
        class_info = self.class_types.get(obj.type)
        if class_info is None:
            raise NotImplementedError("member access only supported on class instances")
        field_index = class_info.field_index(member.name)
        ptr = self.builder.gep(obj, [self.i32(0), self.i32(field_index)], inbounds=True)
        return self.builder.load(ptr)

    def compile_member_store(self, member: Member, value: ir.Value) -> None:
        assert self.builder is not None
        obj = self.compile_expr(member.obj)
        class_info = self.class_types.get(obj.type)
        if class_info is None:
            raise NotImplementedError("member access only supported on class instances")
        field_index = class_info.field_index(member.name)
        ptr = self.builder.gep(
            obj, [self.i32(0), self.i32(field_index)], inbounds=True
        )
        self.builder.store(
            self.coerce(value, class_info.struct_type.elements[field_index]),
            ptr,
        )

    def compile_method_call(self, member: Member, args: list[CallArg]) -> ir.Value:
        assert self.builder is not None
        if member.name != "format":
            receiver = self.compile_expr(member.obj)
            class_info = self.class_types.get(receiver.type)
            if class_info is None:
                raise NotImplementedError(
                    "only string.format or class methods are supported"
                )
            method = self.module.globals.get(f"{class_info.name}__{member.name}")
            if not isinstance(method, ir.Function):
                raise NotImplementedError("unknown method")
            call_args = [receiver] + [self.compile_expr(arg.value) for arg in args]
            param_types = list(method.function_type.args)
            if len(param_types) != len(call_args):
                raise NotImplementedError("argument count mismatch")
            coerced_args = [
                self.coerce(arg, ptype)
                for arg, ptype in zip(call_args, param_types, strict=False)
            ]
            return self.builder.call(method, coerced_args)
        if len(args) != 1:
            raise NotImplementedError("format expects exactly one argument")
        receiver = self.compile_expr(member.obj)
        arg = self.compile_expr(args[0].value)
        if receiver.type != self.i8.as_pointer() or arg.type != self.i8.as_pointer():
            raise NotImplementedError("format supports only string argument")
        callee = self.get_format1()
        return self.builder.call(callee, [receiver, arg])

    def get_alloc(self) -> ir.Function:
        callee = self.module.globals.get("vexil_alloc")
        if not isinstance(callee, ir.Function):
            callee = ir.Function(
                self.module,
                ir.FunctionType(self.i8.as_pointer(), [self.i32]),
                name="vexil_alloc",
            )
        return callee

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
            pattern = arm.pattern
            self.builder.position_at_end(current_block)

            if isinstance(pattern, (WildcardPattern, VarPattern)):
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

            if isinstance(pattern, (WildcardPattern, VarPattern)):
                has_fallthrough = False
                break

        if has_fallthrough:
            raise NotImplementedError("non-exhaustive match expression")

        self.builder.position_at_end(end_block)
        return self.builder.load(result_slot)

    def compile_enum_match(
        self,
        subject: ir.Value,
        enum_info: EnumInfo,
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
            variant: VariantInfo | None = None

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
                assert variant is not None
                for idx, pat in enumerate(pattern.args):
                    if not isinstance(pat, VarPattern):
                        raise NotImplementedError(
                            "only variable patterns are supported for enum fields"
                        )
                    field_type = variant.fields[idx]
                    raw_val = self.builder.extract_value(subject, idx + 1)
                    field_val = self.unpack_enum_payload(raw_val, field_type)
                    slot = self.builder.alloca(field_type, name=pat.name)
                    self.builder.store(field_val, slot)
                    self.allocas[pat.name] = slot
                    self.var_types[pat.name] = field_type

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
    fields: list[ir.Type]

    @property
    def arity(self) -> int:
        return len(self.fields)


@dataclass(frozen=True)
class EnumInfo:
    name: str
    ir_type: ir.LiteralStructType
    variants: dict[str, VariantInfo]

    @property
    def max_payload(self) -> int:
        return len(self.ir_type.elements) - 1


@dataclass(frozen=True)
class FieldInfo:
    name: str
    ir_type: ir.Type


@dataclass(frozen=True)
class ClassInfo:
    name: str
    struct_type: ir.LiteralStructType
    fields: list[FieldInfo]

    @property
    def ptr_type(self) -> ir.PointerType:
        return self.struct_type.as_pointer()

    def field_index(self, name: str) -> int:
        for idx, field in enumerate(self.fields):
            if field.name == name:
                return idx
        raise NotImplementedError(f"unknown field {name}")


def emit_object(module: ir.Module) -> bytes:
    binding.initialize_native_target()
    binding.initialize_native_asmprinter()

    llvm_module = binding.parse_assembly(str(module))
    llvm_module.verify()

    target = binding.Target.from_default_triple()
    target_machine = target.create_target_machine()
    return bytes(target_machine.emit_object(llvm_module))


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
            [
                compiler,
                str(obj_path),
                str(runtime_obj),
                "-o",
                str(output_path),
                "-no-pie",
            ],
            check=True,
        )
