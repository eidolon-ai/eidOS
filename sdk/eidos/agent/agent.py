from __future__ import annotations

import inspect
import typing
from dataclasses import dataclass
from typing import Dict, List, TypeVar, Generic

from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from eidos.agent_os import AgentOS
from eidos.cpu.agent_cpu import AgentCPU
from eidos.cpu.conversational_logic_unit import ConversationalLogicUnit, ConversationalSpec
from eidos.system.reference_model import Specable, Reference
from eidos.util.class_utils import fqn
from eidos.util.schema_to_model import schema_to_model


class ProcessContext(BaseModel):
    process_id: str
    callback_url: typing.Optional[str]


class AgentSpec(BaseModel):
    cpu: Reference[AgentCPU] | str = None
    agent_refs: List[str] = []


class Agent(Specable[AgentSpec]):
    cpu: AgentCPU

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        cpus: Dict[str, AgentCPU] = AgentOS.machine.cpus if AgentOS.machine else {}
        if self.spec.cpu is None:
            self.spec.cpu = cpus.get('DEFAULT', Reference[AgentCPU](implementation=fqn(AgentCPU)))
        elif isinstance(self.spec.cpu, str):
            self.spec.cpu = cpus.get(self.spec.cpu)
            if self.spec.cpu is None:
                raise ValueError(f"Could not find CPU {self.spec.cpu}")
        if self.spec.agent_refs:
            if 'logic_units' not in self.spec.cpu.spec:
                self.spec.cpu.spec['logic_units'] = []
            self.spec.cpu.spec['logic_units'].append(Reference[ConversationalLogicUnit](
                implementation=fqn(ConversationalLogicUnit),
                spec=ConversationalSpec(agents=self.spec.agent_refs).model_dump()
            ).model_dump())
        self.cpu = self.spec.cpu.instantiate()


class CodeAgent:
    pass


def register_program(name: str = None, description: str = None, input_model: callable = None, output_model: callable = None):
    return register_action('UNINITIALIZED', name=name, description=description, input_model=input_model, output_model=output_model)


def register_action(*allowed_states: str, name: str = None, description: str = None, input_model: callable = None, output_model: callable = None):
    if not allowed_states:
        raise ValueError("Must specify at least one valid state")
    if 'terminated' in allowed_states:
        raise ValueError("Action cannot transform terminated state")

    return lambda fn: _add_handler(fn, EidolonHandler(
        name=name or fn.__name__,
        description=description or fn.__doc__,
        allowed_states=list(allowed_states),
        fn=fn,
        input_model_fn=input_model or get_input_model,
        output_model_fn=output_model or get_response_model,
    ))


def _add_handler(fn, handler):
    if not inspect.iscoroutinefunction(fn):
        raise ValueError("Handler must be an async function")
    try:
        handlers = getattr(fn, "eidolon_handlers")
    except AttributeError:
        handlers = []
        setattr(fn, "eidolon_handlers", handlers)
    handlers.append(handler)
    return fn


T = TypeVar('T')


class AgentState(BaseModel, Generic[T]):
    name: str
    data: T


def get_input_model(_obj, handler: EidolonHandler) -> BaseModel:
    sig = inspect.signature(handler.fn).parameters
    hints = typing.get_type_hints(handler.fn, include_extras=True)
    fields = {}
    for param, hint in filter(lambda tu: tu[0] != 'return', hints.items()):
        if hasattr(hint, '__metadata__') and isinstance(hint.__metadata__[0], FieldInfo):
            field: FieldInfo = hint.__metadata__[0]
            field.default = sig[param].default
            fields[param] = (hint.__origin__, field)
        else:
            # _empty default isn't being handled by create_model properly (still optional when it should be required)
            default = ... if getattr(sig[param].default, "__name__", None) == '_empty' else sig[param].default
            fields[param] = (hint, default)

    input_model = create_model(f'{handler.name.capitalize()}InputModel', **fields)
    return input_model


def get_response_model(_obj, handler: EidolonHandler) -> BaseModel:
    return typing.get_type_hints(handler.fn, include_extras=True).get('return', typing.Any)


class SpecRefMeta(type):
    def __getitem__(cls, key):
        return SpecRef()[key]

    def __getattr__(self, item):
        return getattr(SpecRef(), item)


class SpecRef(metaclass=SpecRefMeta):
    def __init__(self):
        self._path = []

    def __getitem__(self, item):
        self._path.append(('getitem', item))
        return self

    def __getattr__(self, item):
        if item not in {"shape", "__len__", "_path"}:
            self._path.append(('getattr', item))
            return self

    def __call__(self, _obj, handler: EidolonHandler):
        if not _obj.spec:
            raise ValueError("Spec must be defined")
        rtn = _obj.spec
        for instruction, item in self._path:
            if instruction == 'getitem':
                rtn = rtn[item]
            elif instruction == 'getattr':
                rtn = getattr(rtn, item)
            else:
                raise ValueError(f"Unknown instruction {instruction}")
        return schema_to_model(rtn, f'{handler.name.capitalize()}InputModel')


@dataclass
class EidolonHandler:
    name: str
    description: str
    allowed_states: List[str]
    fn: callable
    input_model_fn: callable
    output_model_fn: callable

    def is_initializer(self):
        return len(self.allowed_states) == 1 and self.allowed_states[0] == 'UNINITIALIZED'