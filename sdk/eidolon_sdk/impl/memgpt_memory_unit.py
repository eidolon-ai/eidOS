import json
import math
from typing import List, Annotated, Optional

from pydantic import BaseModel, Field

from eidolon_sdk.agent_memory import AgentMemory
from eidolon_sdk.cpu.agent_bus import CallContext, BusController, BusEvent
from eidolon_sdk.cpu.llm_message import LLMMessage, SystemMessage
from eidolon_sdk.cpu.llm_unit import AddsMessages
from eidolon_sdk.cpu.logic_unit import LogicUnit, LogicUnitConfig, llm_function
from eidolon_sdk.cpu.memory_unit import MemoryUnit, MemoryUnitConfig
from eidolon_sdk.reference_model import Specable, Reference
from eidolon_sdk.util.class_utils import fqn


RETRIEVAL_QUERY_DEFAULT_PAGE_SIZE = 10


class CoreMemoryConfig(LogicUnitConfig):
    memory_collection: str = Field(default="core_memory")


class CoreMemory(LogicUnit, AddsMessages, Specable[CoreMemoryConfig]):

    def __init__(self, spec: CoreMemoryConfig = None):
        super().__init__(spec)
        self.spec = spec

    def get_messages(self) -> List[LLMMessage]:
        return [SystemMessage(content='''I can use this space in my core memory to keep track of my current tasks and goals.

The answer to the human's question will usually be located somewhere in your archival memory, so keep paging through results until you find enough information to construct an answer.
Do not respond to the human until you have arrived at an answer.''')]

    @llm_function
    async def append_core_memory(self, content: Annotated[str, Field(description="Content to write to the memory. All unicode (including emojis) are supported.")]) -> None:
        """
        Append to the contents of core memory.

        Args:
            content (str): Content to write to the memory. All unicode (including emojis) are supported.

        Returns:
            None is always returned as this function does not produce a response.
        """
        await self.agent_memory.symbolic_memory.insert_one(self.spec.memory_collection, {"memory": content})
        return None

    @llm_function
    async def replace_core_memory(self, old_content: Annotated[str, Field(description="Content to replace in the memory. Must be an exact match.")],
                                  new_content: Annotated[str, Field(description="Content to write to the memory. All unicode (including emojis) are supported.")]) -> None:
        """
        Replace the contents of core memory.

        Args:
            old_content (str): Content to replace in the memory. Must be an exact match.
            new_content (str): Content to write to the memory. All unicode (including emojis) are supported. An empty string will delete the memory.

        Returns:
            None is always returned as this function does not produce a response.
        """
        if new_content == "":
            await self.agent_memory.symbolic_memory.delete(self.spec.memory_collection, {"memory": old_content})
        else:
            await self.agent_memory.symbolic_memory.upsert_one(self.spec.memory_collection, {"memory": new_content}, {"memory": old_content})
        return None

    @llm_function
    async def search_core_memory(self, query: Annotated[str, Field(description="Query to search for in the memory.")],
                                 page: Annotated[int, Field(description="Allows you to page through results. Only use on a follow-up query. Defaults to 0 (first page).")]
                                 ) -> str:
        """
        Search prior conversation history using case-insensitive string matching.

        Args:
            query (str): String to search for.
            page (int): Allows you to page through results. Only use on a follow-up query. Defaults to 0 (first page).

        Returns:
            str: Query result string
             """

        count = RETRIEVAL_QUERY_DEFAULT_PAGE_SIZE
        total = await self.agent_memory.symbolic_memory.count(self.spec.memory_collection, {"memory": query})
        results = [item["memory"] async for item in self.agent_memory.symbolic_memory.find(self.spec.memory_collection, {"memory": query})]
        num_pages = math.ceil(total / count) - 1  # 0 index
        if len(results) == 0:
            results_str = f"No results found."
        else:
            results_pref = f"Showing {len(results)} of {total} results (page {page}/{num_pages}):"
            results_formatted = [f"timestamp: {d['timestamp']}, {d['message']['role']} - {d['message']['content']}" for d in results]
            results_str = f"{results_pref} {json.dumps(results_formatted)}"
        return results_str


class ArchiveMemoryConfig(LogicUnitConfig):
    memory_collection: str = Field(default="archive_memory")


class ArchiveMemory(LogicUnit, Specable[ArchiveMemoryConfig]):
    def __init__(self, spec: ArchiveMemoryConfig = None):
        super().__init__(spec)
        self.spec = spec

    async def append_archival_memory(self, content: str):
        """
        Add to archival memory. Make sure to phrase the memory contents such that it can be easily queried later.

        Args:
            content (str): Content to write to the memory. All unicode (including emojis) are supported.

        Returns:
            Optional[str]: None is always returned as this function does not produce a response.
        """
        await self.agent_memory.symbolic_memory.insert_one(self.spec.memory_collection, {"memory": content})
        return None

    async def archival_memory_search(self, query: str, page: Optional[int] = 0):
        """
        Search archival memory using semantic (embedding-based) search.

        Args:
            query (str): String to search for.
            page (Optional[int]): Allows you to page through results. Only use on a follow-up query. Defaults to 0 (first page).

        Returns:
            str: Query result string
        """
        count = RETRIEVAL_QUERY_DEFAULT_PAGE_SIZE
        total = await self.agent_memory.symbolic_memory.count(self.spec.memory_collection, {"memory": query})
        results = [item["memory"] async for item in self.agent_memory.symbolic_memory.find(self.spec.memory_collection, {"memory": query})]
        num_pages = math.ceil(total / count) - 1  # 0 index
        if len(results) == 0:
            results_str = f"No results found."
        else:
            results_pref = f"Showing {len(results)} of {total} results (page {page}/{num_pages}):"
            results_formatted = [f"timestamp: {d['timestamp']}, {d['message']['role']} - {d['message']['content']}" for d in results]
            results_str = f"{results_pref} {json.dumps(results_formatted)}"
        return results_str


class MemGPTMemoryUnitConfig(MemoryUnitConfig):
    core_memory: Reference[CoreMemory] = Reference(implementation=fqn(CoreMemory))
    archive_memory: Reference[ArchiveMemory] = Reference(implementation=fqn(ArchiveMemory))


class MemGPTMemoryUnit(MemoryUnit, Specable[MemGPTMemoryUnitConfig]):
    def __init__(self, spec: MemGPTMemoryUnitConfig = None):
        super().__init__(spec)
        self.spec = spec

    def initialize(self, **kwargs):
        super().initialize(**kwargs)
        self.cpu.register_logic_unit(self.spec.core_memory.instantiate())
        self.cpu.register_logic_unit(self.spec.archive_memory.instantiate())

    async def processStoreAndFetchEvent(self, call_context: CallContext, messages: List[LLMMessage]):
        self.request_write(BusEvent(
            call_context,
            self.spec.msf_write,
            messages
        ))

    async def writeMessages(self, call_context: CallContext, messages: List[LLMMessage]):
        pass

    async def getConversationHistory(self, call_context: CallContext) -> List[LLMMessage]:
        pass