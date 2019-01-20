import math
import typing

from pywasm import convention
from pywasm import log
from pywasm import num
from pywasm import structure


class Store:
    # The store represents all global state that can be manipulated by WebAssembly programs. It consists of the runtime
    # representation of all instances of functions, tables, memories, and globals that have been allocated during the
    # life time of the abstract machine
    # Syntactically, the store is defined as a record listing the existing instances of each category:
    # store ::= {
    #     funcs funcinst∗
    #     tables tableinst∗
    #     mems meminst∗
    #     globals globalinst∗
    # }
    #
    # Addresses are dynamic, globally unique references to runtime objects, in contrast to indices, which are static,
    # module-local references to their original definitions. A memory address memaddr denotes the abstract address of
    # a memory instance in the store, not an offset inside a memory instance.
    def __init__(self):
        self.funcs: typing.List[FunctionInstance] = []
        self.tables: typing.List[TableInstance] = []
        self.mems: typing.List[MemoryInstance] = []
        self.globals: typing.List[GlobalInstance] = []


class FunctionInstance:
    # A function instance is the runtime representation of a function. It effectively is a closure of the original
    # function over the runtime module instance of its originating module. The module instance is used to resolve
    # references to other definitions during execution of the function.
    #
    # funcinst ::= {type functype,module moduleinst,code func}
    #            | {type functype,hostcode hostfunc}
    # hostfunc ::= ...
    pass


class WasmFunc(FunctionInstance):
    def __init__(self,
                 functype: structure.FunctionType,
                 module: 'ModuleInstance',
                 code: structure.Function
                 ):
        self.functype = functype
        self.module = module
        self.code = code


class HostFunc(FunctionInstance):
    # A host function is a function expressed outside WebAssembly but passed to a module as an import. The definition
    # and behavior of host functions are outside the scope of this specification. For the purpose of this
    # specification, it is assumed that when invoked, a host function behaves non-deterministically, but within certain
    # constraints that ensure the integrity of the runtime.
    def __init__(self, functype: structure.FunctionType, hostcode: typing.Callable):
        self.functype = functype
        self.hostcode = hostcode


class TableInstance:
    # A table instance is the runtime representation of a table. It holds a vector of function elements and an optional
    # maximum size, if one was specified in the table type at the table’s definition site.
    #
    # Each function element is either empty, representing an uninitialized table entry, or a function address. Function
    # elements can be mutated through the execution of an element segment or by external means provided by the embedder.
    #
    # tableinst ::= {elem vec(funcelem), max u32?}
    # funcelem ::= funcaddr?
    #
    # It is an invariant of the semantics that the length of the element vector never exceeds the maximum size, if
    # present.
    def __init__(self, elemtype: int, limits: structure.Limits):
        self.elemtype = elemtype
        self.limits = limits
        self.elem = [None for _ in range(limits.minimum)]


class MemoryInstance:
    # A memory instance is the runtime representation of a linear memory. It holds a vector of bytes and an optional
    # maximum size, if one was specified at the definition site of the memory.
    #
    # meminst ::= {data vec(byte), max u32?}
    #
    # The length of the vector always is a multiple of the WebAssembly page size, which is defined to be the constant
    # 65536 – abbreviated 64Ki. Like in a memory type, the maximum size in a memory instance is given in units of this
    # page size.
    #
    # The bytes can be mutated through memory instructions, the execution of a data segment, or by external means
    # provided by the embedder.
    #
    # It is an invariant of the semantics that the length of the byte vector, divided by page size, never exceeds the
    # maximum size, if present.
    def __init__(self, limits: structure.Limits):
        self.limits = limits
        self.size = limits.minimum
        self.data = bytearray([0x00 for _ in range(limits.minimum * 64 * 1024)])

    def grow(self, n: int):
        if self.limits.maximum and self.size + n > self.limits.maximum:
            log.panicln('pywasm: out of memory limit')
        self.data.extend([0 for _ in range(n * 64 * 1024)])
        self.size += n


class GlobalInstance:
    # A global instance is the runtime representation of a global variable. It holds an individual value and a flag
    # indicating whether it is mutable.
    #
    # globalinst ::= {value val, mut mut}
    #
    # The value of mutable globals can be mutated through variable instructions or by external means provided by the
    # embedder.
    def __init__(self, value: 'Value', mut: bool):
        self.value = value
        self.mut = mut


class ExportInstance:
    # An export instance is the runtime representation of an export. It defines the export’s name and the associated
    # external value.
    #
    # exportinst ::= {name name, value externval}
    def __init__(self, name: str, value: 'ExternValue'):
        self.name = name
        self.value = value


class ExternValue:
    # An external value is the runtime representation of an entity that can be imported or exported. It is an address
    # denoting either a function instance, table instance, memory instance, or global instances in the shared store.
    #
    # externval ::= func funcaddr
    #             | table tableaddr
    #             | mem memaddr
    #             | global globaladdr
    def __init__(self, extern_type: int, addr: int):
        self.extern_type = extern_type
        self.addr = addr


class Value:
    # Values are represented by themselves.
    def __init__(self, valtype: int, n):
        self.valtype = valtype
        self.n = n

    def __repr__(self):
        return str(self.n)

    @classmethod
    def from_i32(cls, n):
        return Value(convention.i32, n)

    @classmethod
    def from_i64(cls, n):
        return Value(convention.i64, n)

    @classmethod
    def from_f32(cls, n):
        return Value(convention.f32, n)

    @classmethod
    def from_f64(cls, n):
        return Value(convention.f64, n)


class Label:
    # Labels carry an argument arity n and their associated branch target, which is expressed syntactically as an
    # instruction sequence:
    #
    # label ::= labeln{instr∗}
    #
    # Intuitively, instr∗ is the continuation to execute when the branch is taken, in place of the original control
    # construct.
    pass


class Frame:
    # Activation frames carry the return arity of the respective function, hold the values of its locals (including
    # arguments) in the order corresponding to their static local indices, and a reference to the function’s own module
    # instance:
    #
    # activation ::= framen{frame}
    # frame ::= {locals val∗, module moduleinst}
    def __init__(self, module: 'ModuleInstance', locs: typing.List[Value]):
        self.module = module
        self.locals = locs


class Stack:
    # Besides the store, most instructions interact with an implicit stack. The stack contains three kinds of entries:
    #
    # Values: the operands of instructions.
    # Labels: active structured control instructions that can be targeted by branches.
    # Activations: the call frames of active function calls.
    #
    # These entries can occur on the stack in any order during the execution of a program. Stack entries are described
    # by abstract syntax as follows.
    def __init__(self):
        self.data = []

    def add(self, e):
        self.data.append(e)

    def pop(self):
        return self.data.pop()

    def len(self):
        return len(self.data)

    def top(self):
        return self.data[-1]


class AdministrativeInstruction:
    pass


class BlockContext:
    pass


class Configuration:
    # A configuration consists of the current store and an executing thread.
    #
    # A thread is a computation over instructions that operates relative to a current frame referring to the home
    # module instance that the computation runs in.
    #
    # config ::= store;thread
    # thread ::= frame;instr∗
    pass


class EvaluationContext:
    # Finally, the following definition of evaluation context and associated structural rules enable reduction inside
    # instruction sequences and administrative forms as well as the propagation of traps.
    pass


def import_matching_limits(limits1: structure.Limits, limits2: structure.Limits):
    n1 = limits1.minimum
    m1 = limits1.maximum
    n2 = limits2.minimum
    m2 = limits2.maximum
    if n1 < n2:
        return False
    if m2 is None or (m1 != None and m2 != None and m1 <= m2):
        return True
    return False


class ModuleInstance:
    # A module instance is the runtime representation of a module. It is created by instantiating a module, and
    # collects runtime representations of all entities that are imported, defined, or exported by the module.
    #
    # moduleinst ::= {
    #     types functype∗
    #     funcaddrs funcaddr∗
    #     tableaddrs tableaddr∗
    #     memaddrs memaddr∗
    #     globaladdrs globaladdr∗
    #     exports exportinst∗
    # }
    def __init__(self):
        self.types: typing.List[structure.FunctionType] = []
        self.funcaddrs: typing.List[int] = []
        self.tableaddrs: typing.List[int] = []
        self.memaddrs: typing.List[int] = []
        self.globaladdrs: typing.List[int] = []
        self.exports: typing.List[ExportInstance] = []

    def instantiate(
        self,
        module: structure.Module,
        store: Store,
        externvals: typing.List[ExternValue] = None,
    ):
        # [TODO] If module is not valid, then panic
        # Assert: module is valid with external types classifying its imports
        for e in module.imports:
            assert e.kind in convention.extern_type
        # Assert: number m of imports is equal to the number n of provided external values
        assert len(module.imports) == len(externvals)
        # Assert: externvals matching imports of module
        for i in range(len(externvals)):
            e = externvals[i]
            assert e.extern_type in convention.extern_type
            if e.extern_type == convention.extern_func:
                a = store.funcs[e.addr]
                b = self.types[module.imports[i].desc]
                assert a.functype.args == b.args
                assert a.functype.rets == b.rets
            elif e.extern_type == convention.extern_table:
                a = store.tables[e.addr]
                b = module.imports[i].desc
                assert a.elemtype == b.elemtype
                assert import_matching_limits(b.limits, a.limits)
            elif e.extern_type == convention.extern_mem:
                a = store.mems[e.addr]
                b = module.imports[i].desc
                assert import_matching_limits(b, a)
            elif e.extern_type == convention.extern_global:
                a = store.globals[e.addr]
                b = module.imports[i].desc
                assert a.value.valtype == b.valtype
        # Let vals be the vector of global initialization values determined by module and externvaln
        auxmod = ModuleInstance()
        auxmod.globaladdrs = [e.addr for e in externvals if e.extern_type == convention.extern_global]
        stack = Stack()
        frame = Frame(auxmod, [])
        vals = []
        for glob in module.globals:
            v = invoke(store, frame, stack, glob.expr, [convention.i32])[0]
            vals.append(v)
        # Allocation
        self.allocate(module, store, externvals, vals)

        frame = Frame(self, [])
        # For each element segment in module.elem, do:
        for e in module.elem:
            offset = invoke(store, frame, stack, e.expr, [convention.i32])
            assert offset.valtype == convention.i32
            t = store.tables[self.tableaddrs[e.tableidx]]
            for i, e in enumerate(e.init):
                t.elem[offset + i] = e
        # For each data segment in module.data, do:
        for e in module.data:
            offset = invoke(store, frame, stack, e.expr, [convention.i32])
            assert offset.valtype == convention.i32
            m = store.mems[self.memaddrs[e.memidx]]
            end = offset + len(e.init)
            assert end <= len(m.data)
            m.data[offset: offset + len(e.init)] = e.init
        # If the start function module.start is not empty, invoke the function instance
        if module.start is not None:
            frame = Frame(self, [])
            func = store.funcs[self.funcaddrs[module.start]]
            invoke(store, frame, stack, func.code.expr, [convention.i32])

    def allocate(
        self,
        module: structure.Module,
        store: Store,
        externvals: typing.List[ExternValue],
        vals: typing.List[Value],
    ):
        self.types = module.types
        # Imports
        self.funcaddrs.extend([e.addr for e in externvals if e.extern_type == convention.extern_func])
        self.tableaddrs.extend([e.addr for e in externvals if e.extern_type == convention.extern_table])
        self.memaddrs.extend([e.addr for e in externvals if e.extern_type == convention.extern_mem])
        self.globaladdrs.extend([e.addr for e in externvals if e.extern_type == convention.extern_global])
        # For each function func in module.funcs, do:
        for func in module.funcs:
            functype = self.types[func.typeidx]
            funcinst = WasmFunc(functype, self, func)
            store.funcs.append(funcinst)
            self.funcaddrs.append(len(store.funcs) - 1)
        # For each table in module.tables, do:
        for table in module.tables:
            tabletype = table.tabletype
            elemtype = tabletype.elemtype
            tableinst = TableInstance(elemtype, tabletype.limits)
            store.tables.append(tableinst)
            self.tableaddrs.append(len(store.tables) - 1)
        # For each memory module.mems, do:
        for mem in module.mems:
            meminst = MemoryInstance(mem.memtype)
            store.mems.append(meminst)
            self.memaddrs.append(len(store.mems) - 1)
        # For each global in module.globals, do:
        for i, glob in enumerate(module.globals):
            val = vals[i]
            if val.valtype != glob.globaltype.valtype:
                log.panicln('pywasm: mismatch valtype')
            globalinst = GlobalInstance(val, glob.globaltype.mut)
            store.globals.append(globalinst)
            self.globaladdrs.append(len(store.globals) - 1)
        # For each export in module.exports, do:
        for i, export in enumerate(module.exports):
            externval = ExternValue(export.kind, export.desc)
            exportinst = ExportInstance(export.name, externval)
            self.exports.append(exportinst)


def invoke(
    store: Store,
    frame: Frame,
    stack: Stack,
    expr: structure.Expression,
    rets: typing.List[int],
):
    module = frame.module
    stack.add(frame)
    if not expr.data:
        log.panicln('pywasm: empty init expr')
    for i in expr.data:
        log.debugln(i)
        opcode = i.code
        if opcode >= convention.unreachable and opcode <= convention.call_indirect:
            if opcode == convention.unreachable:
                log.panicln('pywasm: reached unreachable')
            if opcode == convention.nop:
                continue
            # if opcode == convention.BLOCK:
            #     n, _, _ = wasmi.common.read_leb(code[pc:], 32)
            #     b = f_sec.bmap[pc - 1]
            #     pc += n
            #     ctx.ctack.append([b, stack.i])
            #     continue
            # if opcode == convention.LOOP:
            #     n, _, _ = wasmi.common.read_leb(code[pc:], 32)
            #     b = f_sec.bmap[pc - 1]
            #     pc += n
            #     ctx.ctack.append([b, stack.i])
            #     continue
            # if opcode == convention.IF:
            #     n, _, _ = wasmi.common.read_leb(code[pc:], 32)
            #     b = f_sec.bmap[pc - 1]
            #     pc += n
            #     ctx.ctack.append([b, stack.i])
            #     cond = stack.pop_i32()
            #     if cond:
            #         continue
            #     if b.pos_else == 0:
            #         ctx.ctack.pop()
            #         pc = b.pos_br + 1
            #         continue
            #     pc = b.pos_else
            #     continue
            # if opcode == convention.ELSE:
            #     b, _ = ctx.ctack[-1]
            #     pc = b.pos_br
            #     continue
            # if opcode == convention.END:
            #     b, sp = ctx.ctack.pop()
            #     if isinstance(b, wasmi.section.Code):
            #         if not ctx.ctack:
            #             if f_sig.rets:
            #                 if f_sig.rets[0] != stack.top().valtype:
            #                     raise wasmi.error.WAException('signature mismatch in call_indirect')
            #                 return stack.pop().n
            #             return None
            #         return
            #     if sp < stack.i:
            #         v = stack.pop()
            #         stack.i = sp
            #         stack.add(v)
            #     continue
            # if opcode == convention.BR:
            #     n, c, _ = wasmi.common.read_leb(code[pc:], 32)
            #     pc += n
            #     for _ in range(c):
            #         ctx.ctack.pop()
            #     b, _ = ctx.ctack[-1]
            #     pc = b.pos_br
            #     continue
            # if opcode == convention.BR_IF:
            #     n, br_depth, _ = wasmi.common.read_leb(code[pc:], 32)
            #     pc += n
            #     cond = stack.pop_i32()
            #     if cond:
            #         for _ in range(br_depth):
            #             ctx.ctack.pop()
            #         b, _ = ctx.ctack[-1]
            #         pc = b.pos_br
            #     continue
            # if opcode == convention.BR_TABLE:
            #     n, lcount, _ = wasmi.common.read_leb(code[pc:], 32)
            #     pc += n
            #     depths = []
            #     for c in range(lcount):
            #         n, ldepth, _ = wasmi.common.read_leb(code[pc:], 32)
            #         pc += n
            #         depths.append(ldepth)
            #     n, ddepth, _ = wasmi.common.read_leb(code[pc:], 32)
            #     pc += n
            #     didx = stack.pop_i32()
            #     if didx >= 0 and didx < len(depths):
            #         ddepth = depths[didx]
            #     for _ in range(ddepth):
            #         ctx.ctack.pop()
            #     b, _ = ctx.ctack[-1]
            #     pc = b.pos_br
            #     continue
            # if opcode == convention.RETURN:
            #     while ctx.ctack:
            #         if isinstance(ctx.ctack[-1][0], wasmi.section.Code):
            #             break
            #         ctx.ctack.pop()
            #     b, _ = ctx.ctack[-1]
            #     pc = len(b.expr.data) - 1
            #     continue
            # if opcode == convention.CALL:
            #     n, f_idx, _ = wasmi.common.read_leb(code[pc:], 32)
            #     pc += n
            #     son_f_fun = self.functions[f_idx]
            #     son_f_sig = son_f_fun.signature
            #     if son_f_fun.envb:
            #         name = son_f_fun.module + '.' + son_f_fun.name
            #         func = self.env.import_func[name]
            #         r = func(self.mem, [stack.pop() for _ in son_f_sig.args][::-1])
            #         e = wasmi.stack.Entry(son_f_sig.rets[0], r)
            #         stack.add(e)
            #         continue
            #     pre_locals_data = ctx.locals_data
            #     ctx.locals_data = [stack.pop() for _ in son_f_sig.args][::-1]
            #     self.exec_step(f_idx, ctx)
            #     ctx.locals_data = pre_locals_data
            #     continue
            if opcode == convention.call_indirect:
                if i.immediate_arguments[1] != 0x00:
                    log.println("pywasm: zero byte malformed in call_indirect")
                continue
            #     n, _, _ = wasmi.common.read_leb(code[pc:], 32)
            #     pc += n
            #     n, _, _ = wasmi.common.read_leb(code[pc:], 1)
            #     pc += n
            #     t_idx = stack.pop_i32()
            #     if not 0 <= t_idx < len(self.table[wasmi.spec.valtype.FUNCREF]):
            #         raise wasmi.error.WAException('undefined element index')
            #     f_idx = self.table[wasmi.spec.valtype.FUNCREF][t_idx]
            #     son_f_fun = self.functions[f_idx]
            #     son_f_sig = son_f_fun.signature
            #     a = list(son_f_sig.args)
            #     b = [stack.pop() for _ in son_f_sig.args][::-1]
            #     for i in range(len(a)):
            #         ia = a[i]
            #         ib = b[i]
            #         if not ib or ia != ib.valtype:
            #             raise wasmi.error.WAException('signature mismatch in call_indirect')
            #     pre_locals_data = ctx.locals_data
            #     ctx.locals_data = b
            #     self.exec_step(f_idx, ctx)
            #     ctx.locals_data = pre_locals_data
            #     continue
            continue
        if opcode == convention.drop:
            stack.pop()
            continue
        if opcode == convention.select:
            cond = stack.pop().n
            a = stack.pop()
            b = stack.pop()
            if cond:
                stack.add(b)
            else:
                stack.add(a)
            continue
        if opcode == convention.get_local:
            stack.add(frame.locals[i.immediate_arguments])
            continue
        if opcode == convention.set_local:
            if i.immediate_arguments >= len(frame.locals):
                frame.locals.extend(
                    [Value.from_i32(0) for _ in range(i.immediate_arguments - len(frame.locals) + 1)]
                )
            frame.locals[i.immediate_arguments] = stack.pop()
            continue
        if opcode == convention.tee_local:
            frame.locals[i.immediate_arguments] = stack.top()
            continue
        if opcode == convention.get_global:
            stack.add(store.globals[module.globaladdrs[i.immediate_arguments]])
            continue
        if opcode == convention.set_global:
            store.globals[module.globaladdrs[i.immediate_arguments]] = stack.pop()
            continue
        if opcode >= convention.i32_load and opcode <= convention.grow_memory:
            m = store.mems[module.memaddrs[0]]
            if opcode >= convention.i32_load and opcode <= convention.i64_load32_u:
                a = stack.pop().n + i.immediate_arguments[1]
                if a + convention.info[opcode][2] > len(m.data):
                    raise log.panicln('pywasm: out of bounds memory access')
                if opcode == convention.i32_load:
                    stack.add(Value.from_i32(num.LittleEndian.i32(m.data[a:a + 4])))
                    continue
                if opcode == convention.i64_load:
                    stack.add(Value.from_i64(num.LittleEndian.i64(m.data[a:a + 8])))
                    continue
                if opcode == convention.f32_load:
                    stack.add(Value.from_f32(num.LittleEndian.f32(m.data[a:a + 4])))
                    continue
                if opcode == convention.f64_load:
                    stack.add(Value.from_f64(num.LittleEndian.f64(m.data[a:a + 8])))
                    continue
                if opcode == convention.i32_load8_s:
                    stack.add(Value.from_i32(num.LittleEndian.i8(m.data[a:a + 1])))
                    continue
                if opcode == convention.i32_load8_u:
                    stack.add(Value.from_i32(num.LittleEndian.u8(m.data[a:a + 1])))
                    continue
                if opcode == convention.i32_load16_s:
                    stack.add(Value.from_i32(num.LittleEndian.i16(m.data[a:a + 2])))
                    continue
                if opcode == convention.i32_load16_u:
                    stack.add(Value.from_i32(num.LittleEndian.u16(m.data[a:a + 2])))
                    continue
                if opcode == convention.i64_load8_s:
                    stack.add(Value.from_i64(num.LittleEndian.i8(m.data[a:a + 1])))
                    continue
                if opcode == convention.i64_load8_u:
                    stack.add(Value.from_i64(num.LittleEndian.u8(m.data[a:a + 1])))
                    continue
                if opcode == convention.i64_load16_s:
                    stack.add(Value.from_i64(num.LittleEndian.i16(m.data[a:a + 2])))
                    continue
                if opcode == convention.i64_load16_u:
                    stack.add(Value.from_i64(num.LittleEndian.u16(m.data[a:a + 2])))
                    continue
                if opcode == convention.i64_load32_s:
                    stack.add(Value.from_i64(num.LittleEndian.i32(m.data[a:a + 4])))
                    continue
                if opcode == convention.i64_load32_u:
                    stack.add(Value.from_i64(num.LittleEndian.u32(m.data[a:a + 4])))
                    continue
                continue
            if opcode >= convention.i32_store and opcode <= convention.i64_store32:
                v = stack.pop().n
                a = stack.pop().n + i.immediate_arguments[1]
                if a + convention.info[opcode][2] > len(m.data):
                    raise log.panicln('pywasm: out of bounds memory access')
                if opcode == convention.i32_store:
                    m.data[a:a + 4] = num.LittleEndian.pack_i32(v)
                    continue
                if opcode == convention.i64_store:
                    m.data[a:a + 8] = num.LittleEndian.pack_i64(v)
                    continue
                if opcode == convention.f32_store:
                    m.data[a:a + 4] = num.LittleEndian.pack_f32(v)
                    continue
                if opcode == convention.f64_store:
                    m.data[a:a + 8] = num.LittleEndian.pack_f64(v)
                    continue
                if opcode == convention.i32_store8:
                    m.data[a:a + 1] = num.LittleEndian.pack_i8(num.int2i8(v))
                    continue
                if opcode == convention.i32_store16:
                    m.data[a:a + 2] = num.LittleEndian.pack_i16(num.int2i16(v))
                    continue
                if opcode == convention.i64_store8:
                    m.data[a:a + 1] = num.LittleEndian.pack_i8(num.int2i8(v))
                    continue
                if opcode == convention.i64_store16:
                    m.data[a:a + 2] = num.LittleEndian.pack_i16(num.int2i16(v))
                    continue
                if opcode == convention.i64_store32:
                    m.data[a:a + 4] = num.LittleEndian.pack_i32(num.int2i32(v))
                    continue
                continue
            if opcode == convention.current_memory:
                stack.add(Value.from_i32(m.size))
                continue
            if opcode == convention.grow_memory:
                cursize = m.size
                m.grow(stack.pop().n)
                stack.add(Value.from_i32(cursize))
                continue
            continue
        if opcode >= convention.i32_const and opcode <= convention.f64_const:
            if opcode == convention.i32_const:
                stack.add(Value.from_i32(i.immediate_arguments))
                continue
            if opcode == convention.i64_const:
                stack.add(Value.from_i64(i.immediate_arguments))
                continue
            if opcode == convention.f32_const:
                stack.add(Value.from_f32(i.immediate_arguments))
                continue
            if opcode == convention.f64_const:
                stack.add(Value.from_f64(i.immediate_arguments))
                continue
            continue
        if opcode == convention.i32_eqz:
            stack.add(Value.from_i32(stack.pop().n == 0))
            continue
        if opcode >= convention.i32_eq and opcode <= convention.i32_geu:
            b = stack.pop().n
            a = stack.pop().n
            if opcode == convention.i32_eq:
                stack.add(Value.from_i32(a == b))
                continue
            if opcode == convention.i32_ne:
                stack.add(Value.from_i32(a != b))
                continue
            if opcode == convention.i32_lts:
                stack.add(Value.from_i32(a < b))
                continue
            if opcode == convention.i32_ltu:
                stack.add(Value.from_i32(num.int2u32(a) < num.int2u32(b)))
                continue
            if opcode == convention.i32_gts:
                stack.add(Value.from_i32(a > b))
                continue
            if opcode == convention.i32_gtu:
                stack.add(Value.from_i32(num.int2u32(a) > num.int2u32(b)))
                continue
            if opcode == convention.i32_les:
                stack.add(Value.from_i32(a <= b))
                continue
            if opcode == convention.i32_leu:
                stack.add(Value.from_i32(num.int2u32(a) <= num.int2u32(b)))
                continue
            if opcode == convention.i32_ges:
                stack.add(Value.from_i32(a >= b))
                continue
            if opcode == convention.i32_geu:
                stack.add(Value.from_i32(num.int2u32(a) >= num.int2u32(b)))
                continue
            continue
        if opcode == convention.i64_eqz:
            stack.add(Value.from_i32(stack.pop().n == 0))
            continue
        if opcode >= convention.i64_eq and opcode <= convention.i64_geu:
            b = stack.pop().n
            a = stack.pop().n
            if opcode == convention.i64_eq:
                stack.add(Value.from_i32(a == b))
                continue
            if opcode == convention.i64_ne:
                stack.add(Value.from_i32(a != b))
                continue
            if opcode == convention.i64_lts:
                stack.add(Value.from_i32(a < b))
                continue
            if opcode == convention.i64_ltu:
                stack.add(Value.from_i32(num.int2u64(a) < num.int2u64(b)))
                continue
            if opcode == convention.i64_gts:
                stack.add(Value.from_i32(a > b))
                continue
            if opcode == convention.i64_gtu:
                stack.add(Value.from_i32(num.int2u64(a) > num.int2u64(b)))
                continue
            if opcode == convention.i64_les:
                stack.add(Value.from_i32(a <= b))
                continue
            if opcode == convention.i64_leu:
                stack.add(Value.from_i32(num.int2u64(a) <= num.int2u64(b)))
                continue
            if opcode == convention.i64_ges:
                stack.add(Value.from_i32(a >= b))
                continue
            if opcode == convention.i64_geu:
                stack.add(Value.from_i32(num.int2u64(a) >= num.int2u64(b)))
                continue
            continue
        if opcode >= convention.f32_eq and opcode <= convention.f64_ge:
            b = stack.pop().n
            a = stack.pop().n
            if opcode == convention.f32_eq:
                stack.add(Value.from_i32(a == b))
                continue
            if opcode == convention.f32_ne:
                stack.add(Value.from_i32(a != b))
                continue
            if opcode == convention.f32_lt:
                stack.add(Value.from_i32(a < b))
                continue
            if opcode == convention.f32_gt:
                stack.add(Value.from_i32(a > b))
                continue
            if opcode == convention.f32_le:
                stack.add(Value.from_i32(a <= b))
                continue
            if opcode == convention.f32_ge:
                stack.add(Value.from_i32(a >= b))
                continue
            if opcode == convention.f64_eq:
                stack.add(Value.from_i32(a == b))
                continue
            if opcode == convention.f64_ne:
                stack.add(Value.from_i32(a != b))
                continue
            if opcode == convention.f64_lt:
                stack.add(Value.from_i32(a < b))
                continue
            if opcode == convention.f64_gt:
                stack.add(Value.from_i32(a > b))
                continue
            if opcode == convention.f64_le:
                stack.add(Value.from_i32(a <= b))
                continue
            if opcode == convention.f64_ge:
                stack.add(Value.from_i32(a >= b))
                continue
            continue
        if opcode >= convention.i32_clz and opcode <= convention.i32_popcnt:
            a = stack.pop().n
            if opcode == convention.i32_clz:
                c = 0
                while c < 32 and (a & 0x80000000) == 0:
                    c += 1
                    a *= 2
                stack.add(Value.from_i32(c))
                continue
            if opcode == convention.i32_ctz:
                c = 0
                while c < 32 and (a % 2) == 0:
                    c += 1
                    a /= 2
                stack.add(Value.from_i32(c))
                continue
            if opcode == convention.i32_popcnt:
                c = 0
                for i in range(32):
                    if 0x1 & a:
                        c += 1
                    a /= 2
                stack.add(Value.from_i32(c))
                continue
            continue
        if opcode >= convention.i32_add and opcode <= convention.i32_rotr:
            b = stack.pop().n
            a = stack.pop().n
            if opcode in [
                convention.i32_divs,
                convention.i32_divu,
                convention.i32_rems,
                convention.i32_remu,
            ]:
                if b == 0:
                    log.panicln('pywasm: integer divide by zero')
            if opcode == convention.i32_add:
                stack.add(Value.from_i32(num.int2i32(a + b)))
                continue
            if opcode == convention.i32_sub:
                stack.add(Value.from_i32(num.int2i32(a - b)))
                continue
            if opcode == convention.i32_mul:
                stack.add(Value.from_i32(num.int2i32(a * b)))
                continue
            if opcode == convention.i32_divs:
                if a == 0x80000000 and b == -1:
                    log.panicln('pywasm: integer overflow')
                stack.add(Value.from_i32(num.idiv_s(a, b)))
                continue
            if opcode == convention.i32_divu:
                stack.add(Value.from_i32(num.int2i32(num.int2u32(a) // num.int2u32(b))))
                continue
            if opcode == convention.i32_rems:
                stack.add(Value.from_i32(num.irem_s(a, b)))
                continue
            if opcode == convention.i32_remu:
                stack.add(Value.from_i32(num.int2i32(num.int2u32(a) % num.int2u32(b))))
                continue
            if opcode == convention.i32_and:
                stack.add(Value.from_i32(a & b))
                continue
            if opcode == convention.i32_or:
                stack.add(Value.from_i32(a | b))
                continue
            if opcode == convention.i32_xor:
                stack.add(Value.from_i32(a ^ b))
                continue
            if opcode == convention.i32_shl:
                stack.add(Value.from_i32(a << (b % 0x20)))
                continue
            if opcode == convention.i32_shrs:
                stack.add(Value.from_i32(a >> (b % 0x20)))
                continue
            if opcode == convention.i32_shru:
                stack.add(Value.from_i32(num.int2u32(a) >> (b % 0x20)))
                continue
            if opcode == convention.i32_rotl:
                stack.add(Value.from_i32(num.int2i32(num.rotl_u32(a, b))))
                continue
            if opcode == convention.i32_rotr:
                stack.add(Value.from_i32(num.int2i32(num.rotr_u32(a, b))))
                continue
            continue
        if opcode >= convention.i64_clz and opcode <= convention.i64_popcnt:
            a = stack.pop().n
            if opcode == convention.i64_clz:
                if a < 0:
                    stack.add(Value.from_i32(0))
                    continue
                c = 1
                while c < 63 and (a & 0x4000000000000000) == 0:
                    c += 1
                    a *= 2
                stack.add(Value.from_i64(c))
                continue
            if opcode == convention.i64_ctz:
                c = 0
                while c < 64 and (a % 2) == 0:
                    c += 1
                    a /= 2
                stack.add(Value.from_i64(c))
                continue
            if opcode == convention.i64_popcnt:
                c = 0
                for i in range(64):
                    if 0x1 & a:
                        c += 1
                    a /= 2
                stack.add(Value.from_i64(c))
                continue
            continue
        if opcode >= convention.i64_add and opcode <= convention.i64_rotr:
            b = stack.pop().n
            a = stack.pop().n
            if opcode in [
                convention.i64_divs,
                convention.i64_divu,
                convention.i64_rems,
                convention.i64_remu,
            ]:
                if b == 0:
                    raise log.panicln('pywasm: integer divide by zero')
            if opcode == convention.i64_add:
                stack.add(Value.from_i64(num.int2i64(a + b)))
                continue
            if opcode == convention.i64_sub:
                stack.add(Value.from_i64(num.int2i64(a - b)))
                continue
            if opcode == convention.i64_mul:
                stack.add(Value.from_i64(num.int2i64(a * b)))
                continue
            if opcode == convention.i64_divs:
                stack.add(Value.from_i64(num.idiv_s(a, b)))
                continue
            if opcode == convention.i64_divu:
                stack.add(Value.from_i64(num.int2i64(num.int2u64(a) // num.int2u64(b))))
                continue
            if opcode == convention.i64_rems:
                stack.add(Value.from_i64(num.irem_s(a, b)))
            if opcode == convention.i64_remu:
                stack.add(Value.from_i64(num.int2u64(a) % num.int2u64(b)))
                continue
            if opcode == convention.i64_and:
                stack.add(Value.from_i64(a & b))
                continue
            if opcode == convention.i64_or:
                stack.add(Value.from_i64(a | b))
                continue
            if opcode == convention.i64_xor:
                stack.add(Value.from_i64(a ^ b))
                continue
            if opcode == convention.i64_shl:
                stack.add(Value.from_i64(a << (b % 0x40)))
                continue
            if opcode == convention.i64_shrs:
                stack.add(Value.from_i64(a >> (b % 0x40)))
                continue
            if opcode == convention.i64_shru:
                stack.add(Value.from_i64(num.int2u64(a) >> (b % 0x40)))
                continue
            if opcode == convention.i64_rotl:
                stack.add(Value.from_i64(num.int2i64(num.rotl_u64(a, b))))
                continue
            if opcode == convention.i64_rotr:
                stack.add(Value.from_i64(num.int2i64(num.rotr_u64(a, b))))
                continue
            continue
        if opcode >= convention.f32_abs and opcode <= convention.f32_sqrt:
            a = stack.pop().n
            if opcode == convention.f32_abs:
                stack.add(Value.from_f32(abs(a)))
                continue
            if opcode == convention.f32_neg:
                stack.add(Value.from_f32(-a))
                continue
            if opcode == convention.f32_ceil:
                stack.add(Value.from_f32(math.ceil(a)))
                continue
            if opcode == convention.f32_floor:
                stack.add(Value.from_f32(math.floor(a)))
                continue
            if opcode == convention.f32_trunc:
                stack.add(Value.from_f32(math.trunc(a)))
                continue
            if opcode == convention.f32_nearest:
                ceil = math.ceil(a)
                if ceil - a >= 0.5:
                    r = ceil
                else:
                    r = ceil - 1
                stack.add(Value.from_f32(r))
                continue
            if opcode == convention.f32_sqrt:
                stack.add(Value.from_f32(math.sqrt(a)))
                continue
            continue
        if opcode >= convention.f32_add and opcode <= convention.f32_copysign:
            b = stack.pop().n
            a = stack.pop().n
            if opcode == convention.f32_add:
                stack.add(Value.from_f32(a + b))
                continue
            if opcode == convention.f32_sub:
                stack.add(Value.from_f32(a - b))
                continue
            if opcode == convention.f32_mul:
                stack.add(Value.from_f32(a * b))
                continue
            if opcode == convention.f32_div:
                stack.add(Value.from_f32(a / b))
                continue
            if opcode == convention.f32_min:
                stack.add(Value.from_f32(min(a, b)))
                continue
            if opcode == convention.f32_max:
                stack.add(Value.from_f32(max(a, b)))
                continue
            if opcode == convention.f32_copysign:
                stack.add(Value.from_f32(math.copysign(a, b)))
                continue
            continue
        if opcode >= convention.f64_abs and opcode <= convention.f64_sqrt:
            a = stack.pop().n
            if opcode == convention.f64_abs:
                stack.add(Value.from_f64(abs(a)))
                continue
            if opcode == convention.f64_neg:
                stack.add(Value.from_f64(-a))
                continue
            if opcode == convention.f64_ceil:
                stack.add(Value.from_f64(math.ceil(a)))
                continue
            if opcode == convention.f64_floor:
                stack.add(Value.from_f64(math.floor(a)))
                continue
            if opcode == convention.f64_trunc:
                stack.add(Value.from_f64(math.trunc(a)))
                continue
            if opcode == convention.f64_nearest:
                ceil = math.ceil(a)
                if ceil - a >= 0.5:
                    r = ceil
                else:
                    r = ceil - 1
                stack.add(Value.from_f64(r))
                continue
            if opcode == convention.f64_sqrt:
                stack.add(Value.from_f64(math.sqrt(a)))
                continue
            continue
        if opcode >= convention.f64_add and opcode <= convention.f64_copysign:
            b = stack.pop().n
            a = stack.pop().n
            if opcode == convention.f64_add:
                stack.add(Value.from_f64(a + b))
                continue
            if opcode == convention.f64_sub:
                stack.add(Value.from_f64(a - b))
                continue
            if opcode == convention.f64_mul:
                stack.add(Value.from_f64(a * b))
                continue
            if opcode == convention.f64_div:
                stack.add(Value.from_f64(a / b))
                continue
            if opcode == convention.f64_min:
                stack.add(Value.from_f64(min(a, b)))
                continue
            if opcode == convention.f64_max:
                stack.add(Value.from_f64(max(a, b)))
                continue
            if opcode == convention.f64_copysign:
                stack.add(Value.from_f64(math.copysign(a, b)))
                continue
            continue
        if opcode >= convention.i32_wrap_i64 and opcode <= convention.f64_promote_f32:
            a = stack.pop().n
            if opcode in [
                convention.i32_trunc_sf32,
                convention.i32_trunc_uf32,
                convention.i32_trunc_sf64,
                convention.i32_trunc_uf64,
                convention.i64_trunc_sf32,
                convention.i64_trunc_uf32,
                convention.i64_trunc_sf64,
                convention.i64_trunc_uf64,
            ]:
                if math.isnan(a):
                    log.panicln('pywasm: invalid conversion to integer')
            if opcode == convention.i32_wrap_i64:
                stack.add(Value.from_i32(num.int2i32(a)))
                continue
            if opcode == convention.i32_trunc_sf32:
                if a > 2**31 - 1 or a < -2**32:
                    log.panicln('pywasm: integer overflow')
                stack.add(Value.from_i32(int(a)))
                continue
            if opcode == convention.i32_trunc_uf32:
                if a > 2**32 - 1 or a < -1:
                    log.panicln('pywasm: integer overflow')
                stack.add(Value.from_i32(int(a)))
                continue
            if opcode == convention.i32_trunc_sf64:
                if a > 2**31 - 1 or a < -2**32:
                    log.panicln('pywasm: integer overflow')
                stack.add(Value.from_i32(int(a)))
                continue
            if opcode == convention.i32_trunc_uf64:
                if a > 2**32 - 1 or a < -1:
                    log.panicln('pywasm: integer overflow')
                stack.add(Value.from_i32(int(a)))
                continue
            if opcode == convention.i64_extend_si32:
                stack.add(Value.from_i64(a))
                continue
            if opcode == convention.i64_extend_ui32:
                stack.add(Value.from_i64(num.int2u32(a)))
                continue
            if opcode == convention.i64_trunc_sf32:
                if a > 2**63 - 1 or a < -2**63:
                    log.panicln('pywasm: integer overflow')
                stack.add(Value.from_i64(int(a)))
                continue
            if opcode == convention.i64_trunc_uf32:
                if a > 2**63 - 1 or a < -1:
                    log.panicln('pywasm: integer overflow')
                stack.add(Value.from_i64(int(a)))
                continue
            if opcode == convention.i64_trunc_sf64:
                stack.add(Value.from_i64(int(a)))
                continue
            if opcode == convention.i64_trunc_uf64:
                if a < -1:
                    log.panicln('pywasm: integer overflow')
                stack.add(Value.from_i64(int(a)))
                continue
            if opcode == convention.f32_convert_si32:
                stack.add(Value.from_f32(a))
                continue
            if opcode == convention.f32_convert_ui32:
                stack.add(Value.from_f32(num.int2u32(a)))
                continue
            if opcode == convention.f32_convert_si64:
                stack.add(Value.from_f32(a))
                continue
            if opcode == convention.f32_convert_ui64:
                stack.add(Value.from_f32(num.int2u64(a)))
                continue
            if opcode == convention.f32_demote_f64:
                stack.add(Value.from_f32(a))
                continue
            if opcode == convention.f64_convert_si32:
                stack.add(Value.from_f64(a))
                continue
            if opcode == convention.f64_convert_ui32:
                stack.add(Value.from_f64(num.int2u32(a)))
                continue
            if opcode == convention.f64_convert_si64:
                stack.add(Value.from_f64(a))
                continue
            if opcode == convention.f64_convert_ui64:
                stack.add(Value.from_f64(num.int2u64(a)))
                continue
            if opcode == convention.f64_promote_f32:
                stack.add(Value.from_f64(a))
                continue
            continue
        if opcode >= convention.i32_reinterpret_f32 and opcode <= convention.f64_reinterpret_i64:
            a = stack.pop().n
            if opcode == convention.i32_reinterpret_f32:
                stack.add(Value.from_i32(num.f322i32(a)))
                continue
            if opcode == convention.i64_reinterpret_f64:
                stack.add(Value.from_i64(num.f642i64(a)))
                continue
            if opcode == convention.f32_reinterpret_i32:
                stack.add(Value.from_f32(num.i322f32(a)))
                continue
            if opcode == convention.f64_reinterpret_i64:
                stack.add(Value.from_f64(num.i642f64(a)))
                continue
            continue

    r = [stack.pop() for _ in rets]
    assert isinstance(stack.pop(), Frame)
    return r
