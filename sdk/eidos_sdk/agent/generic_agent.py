from typing import Annotated, Dict, Any, Literal, Type, Union

from fastapi import Body
from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel, field_validator, Field

from eidos_sdk.agent.agent import (
    Agent,
    register_action,
    AgentState,
    AgentSpec,
    register_program,
)
from eidos_sdk.system.eidos_handler import EidosHandler
from eidos_sdk.cpu.agent_io import UserTextCPUMessage, SystemCPUMessage, ImageCPUMessage
from eidos_sdk.system.reference_model import Specable
from eidos_sdk.util.schema_to_model import schema_to_model


class GenericAgentSpec(AgentSpec):
    description: str
    system_prompt: str
    user_prompt: str
    input_schema: Dict[str, Any] = Field({}, description="The json schema for the input model.")
    output_schema: Union[Literal["str"], Dict[str, Any]] = Field(
        default="str", description="The json schema for the output model or the literal 'str' for text output."
    )
    files: Literal["disable", "single", "single-optional", "multiple"] = "disable"

    @field_validator("input_schema")
    def validate_prompt_properties(cls, input_dict):
        if not isinstance(input_dict, dict):
            raise ValueError("prompt_properties must be a dict")
        for k, v in input_dict.items():
            if isinstance(v, dict):
                if v.get("format") == "binary":
                    raise ValueError(
                        "prompt_properties cannot contain format = 'binary' fields. Use the files option instead"
                    )
        return input_dict


class LlmResponse(BaseModel):
    response: str


def make_description(agent: object, _handler: EidosHandler) -> str:
    # noinspection PyUnresolvedReferences
    spec = agent.spec
    return spec.description


def make_input_schema(agent: object, handler: EidosHandler) -> Type[BaseModel]:
    # noinspection PyUnresolvedReferences
    spec = agent.spec
    properties: Dict[str, Any] = {}
    if spec.input_schema:
        properties["body"] = dict(
            type="object",
            properties=spec.input_schema,
        )
    required = ["body"]
    if spec.files == "single" or spec.files == "single-optional":
        properties["file"] = dict(type="string", format="binary")
        if spec.files == "single":
            required.append("file")
    elif spec.files == "multiple":
        properties["file"] = dict(type="array", items=dict(type="string", format="binary"))
        required.append("file")
    elif "files" in properties:
        del properties["file"]
    schema = {"type": "object", "properties": properties, "required": required}
    return schema_to_model(schema, f"{handler.name.capitalize()}InputModel")


def make_output_schema(agent: object, handler: EidosHandler) -> Type[Any]:
    # noinspection PyUnresolvedReferences
    spec = agent.spec
    if spec.output_schema == "str":
        return str
    elif spec.output_schema:
        return schema_to_model(spec.output_schema, f"{handler.name.capitalize()}OutputModel")
    else:
        raise ValueError("output_schema must be specified")


class GenericAgent(Agent, Specable[GenericAgentSpec]):
    @register_program(
        input_model=make_input_schema,
        output_model=make_output_schema,
        description=make_description,
    )
    async def question(self, process_id, **kwargs) -> AgentState[Any]:
        body = kwargs.get("body")
        body = dict(body) if body else {}
        files = kwargs.get("file", [])
        if not isinstance(files, list):
            files = [files]
        env = Environment(undefined=StrictUndefined)
        t = await self.cpu.main_thread(process_id)
        await t.set_boot_messages(
            output_format=self.spec.output_schema,
            prompts=[SystemCPUMessage(prompt=(env.from_string(self.spec.system_prompt).render(**body)))],
        )

        # pull out any kwargs that are UploadFile and put them in a list of UserImageCPUMessage
        image_messages = []
        for file in files:
            if file:
                image_messages.append(ImageCPUMessage(image=file.file, prompt=file.filename))

        response = await t.schedule_request(
            prompts=[
                UserTextCPUMessage(prompt=(env.from_string(self.spec.user_prompt).render(**body))),
                *image_messages,
            ],
            output_format=self.spec.output_schema,
        )
        return AgentState(name="idle", data=response)

    @register_action("idle")
    async def respond(self, process_id, statement: Annotated[str, Body(embed=True)]) -> AgentState[Any]:
        t = await self.cpu.main_thread(process_id)
        response = await t.schedule_request([UserTextCPUMessage(prompt=statement)], self.spec.output_schema)
        return AgentState(name="idle", data=response)
