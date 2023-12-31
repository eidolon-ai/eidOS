import logging
from typing import List

from eidos_sdk.agent_os import AgentOS
from eidos_sdk.cpu.call_context import CallContext
from eidos_sdk.cpu.llm_message import LLMMessage
from eidos_sdk.cpu.memory_unit import MemoryUnit, MemoryUnitConfig
from eidos_sdk.system.reference_model import Specable


class RawMemoryUnit(MemoryUnit, Specable[MemoryUnitConfig]):
    async def writeMessages(self, call_context: CallContext, messages: List[LLMMessage]):
        conversationItems = [
            {
                "process_id": call_context.process_id,
                "thread_id": call_context.thread_id,
                "message": message.model_dump(),
                "is_boot_message": False,
            }
            for message in messages
        ]

        logging.debug(str(messages))
        logging.debug(conversationItems)

        await AgentOS.symbolic_memory.insert("conversation_memory", conversationItems)

    async def writeBootMessages(self, call_context: CallContext, messages: List[LLMMessage]):
        conversationItems = [
            {
                "process_id": call_context.process_id,
                "thread_id": call_context.thread_id,
                "message": message.model_dump(),
                "is_boot_message": True,
            }
            for message in messages
        ]

        logging.debug(str(messages))
        logging.debug(conversationItems)

        await AgentOS.symbolic_memory.insert("conversation_memory", conversationItems)

    async def getConversationHistory(self, call_context: CallContext) -> List[LLMMessage]:
        existingMessages = []
        async for message in AgentOS.symbolic_memory.find(
            "conversation_memory",
            {
                "process_id": call_context.process_id,
                "thread_id": call_context.thread_id,
                "is_boot_message": True,
            },
            {"is_boot_message": 0},
        ):
            existingMessages.append(LLMMessage.from_dict(message["message"]))
        async for message in AgentOS.symbolic_memory.find(
            "conversation_memory",
            {
                "process_id": call_context.process_id,
                "thread_id": call_context.thread_id,
                "is_boot_message": False,
            },
            {"is_boot_message": 0},
        ):
            existingMessages.append(LLMMessage.from_dict(message["message"]))

        logging.debug("existingMessages = " + str(existingMessages))
        return existingMessages
