from abc import ABC, abstractmethod
from typing import Any, Optional, Iterable, AsyncIterable

import numpy as np
from pydantic import BaseModel, Field, field_validator

from eidolon_sdk.util.class_utils import for_name
from eidolon_sdk.util.str_utils import replace_env_var_in_string


# todo, memory contracts all need to be async
class FileMemory(BaseModel, ABC):
    implementation: str

    """
    Abstract base class representing the file memory interface for an agent.

    This class defines the essential file operations that an agent's memory component
    must support. It includes starting and stopping the file memory processes,
    reading from a file, and writing to a file within the agent's operational context.

    All methods in this class are abstract and must be implemented by a subclass
    that provides the specific logic for handling file operations related to the
    agent's memory.
    """

    @abstractmethod
    def start(self):
        """
        Starts the memory implementation.
        """
        pass

    @abstractmethod
    def stop(self):
        """
        Stops the memory implementation.
        """
        pass

    @abstractmethod
    def read_file(self, file_path: str) -> bytes:
        """
            Reads the contents of a file specified by `file_path` within the context
            of an agent call. The context of the call provides additional information
            that may influence how the file is read.
        :param file_path: The path to the file to be read.
        :return: bytes: The contents of the file as a bytes object.
        """
        pass

    @abstractmethod
    def write_file(self, file_path: str, file_contents: bytes) -> None:
        """
            Writes the given `file_contents` to the file specified by `file_path`
            within the context of an agent call. This method ensures that the file is
            written in the appropriate location and manner as dictated by the call context.

        :param file_path: The path to the file where the contents should be written.
        :param file_contents: The contents to write to the file.
        """
        pass


class SymbolicMemory(BaseModel, ABC):
    implementation: str

    """
    Abstract base class for a symbolic memory component within an agent.

    This class defines the contract for symbolic memory operations such as starting
    and stopping the memory service, and CRUD (Create, Read, Update, Delete) operations
    on symbolic data. Implementations of this class are expected to manage collections
    of symbols, providing a high-level interface to store and retrieve symbolic information.
    """

    @abstractmethod
    def start(self):
        """
        Prepares the symbolic memory for operation, which may include tasks like
        allocating resources or initializing connections to databases.
        """
        pass

    @abstractmethod
    def stop(self):
        """
        Properly shuts down the symbolic memory, ensuring that any resources are released
        or any established connections are terminated.
        """
        pass

    @abstractmethod
    def find(self, symbol_collection: str, query: dict[str, Any]) -> AsyncIterable[dict[str, Any]]:
        """
        Searches for symbols within a specified collection that match the given query.

        Args:
            symbol_collection (str): The name of the collection to search within.
            query (dict[str, Any]): The search criteria used to filter symbols.

        Returns:
            Iterable[dict[str, Any]]: A list of symbols that match the query, each represented as a dictionary.
        """
        pass

    @abstractmethod
    async def find_one(self, symbol_collection: str, query: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        Searches for a single symbol within a specified collection that matches the given query.

        Args:
            symbol_collection (str): The name of the collection to search within.
            query (dict[str, Any]): The search criteria used to filter symbols.

        Returns:
            Optional[dict[str, Any]]: A single symbol that matches the query, represented as a dictionary,
            or None if no match is found.
        """
        pass

    @abstractmethod
    async def insert(self, symbol_collection: str, documents: list[dict[str, Any]]) -> None:
        """
        Inserts multiple symbols into the specified collection.

        Args:
            symbol_collection (str): The name of the collection where symbols will be inserted.
            documents (list[dict[str, Any]]): A list of symbols to insert, each represented as a dictionary.

        Returns:
            None
        """
        pass

    @abstractmethod
    async def insert_one(self, symbol_collection: str, document: dict[str, Any]) -> None:
        """
        Inserts a single symbol into the specified collection.

        Args:
            symbol_collection (str): The name of the collection where the symbol will be inserted.
            document (dict[str, Any]): The symbol to insert, represented as a dictionary.

        Returns:
            None
        """
        pass

    @abstractmethod
    async def upsert_one(self, symbol_collection: str, document: dict[str, Any], query: dict[str, Any]) -> None:
        """
        Updates a single symbol in the specified collection based on the query, or inserts it if it does not exist.

        Args:
            symbol_collection (str): The name of the collection where the symbol will be upserted.
            document (dict[str, Any]): The symbol to upsert, represented as a dictionary.
            query (dict[str, Any]): The search criteria used to find the symbol to update.

        Returns:
            None
        """
        pass


class SimilarityMemory(BaseModel, ABC):
    implementation: str

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def stop(self):
        pass

    @abstractmethod
    async def query(self, query: np.array) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def insert(self, embedding: np.array) -> None:
        pass


# todo, we need base models for memory to represent configuration, not implementation as well.
class AgentMemory(BaseModel):
    file_memory: FileMemory = Field(default=None, description="The File Memory implementation.")
    symbolic_memory: SymbolicMemory = Field(default=None, description="The Symbolic Memory implementation.")
    similarity_memory: SimilarityMemory = Field(default=None, description="The Similarity Memory implementation.")

    @field_validator('file_memory', mode='before')
    def validate_file_memory(cls, value):
        implementation_name = replace_env_var_in_string(value.get('implementation') if isinstance(value, dict) else value.implementation)
        implementation_class = for_name(implementation_name, FileMemory)
        if isinstance(value, dict):
            return implementation_class(**value)
        else:
            return implementation_class(**value.model_dump())

    @field_validator('symbolic_memory', mode='before')
    def validate_symbolic_memory(cls, value):
        implementation_name = replace_env_var_in_string(value.get('implementation') if isinstance(value, dict) else value.implementation)
        implementation_class = for_name(implementation_name, SymbolicMemory)
        if isinstance(value, dict):
            return implementation_class(**value)
        else:
            return implementation_class(**value.model_dump())

    @field_validator('similarity_memory', mode='before')
    def validate_similarity_memory(cls, value):
        implementation_name = replace_env_var_in_string(value.get('implementation') if isinstance(value, dict) else value.implementation)
        implementation_class = for_name(implementation_name, SimilarityMemory)
        if isinstance(value, dict):
            return implementation_class(**value)
        else:
            return implementation_class(**value.model_dump())

    def start(self):
        if self.file_memory:
            self.file_memory.start()
        if self.symbolic_memory:
            self.symbolic_memory.start()
        if self.similarity_memory:
            self.similarity_memory.start()

    def stop(self):
        if self.file_memory:
            self.file_memory.stop()
        if self.symbolic_memory:
            self.symbolic_memory.stop()
        if self.similarity_memory:
            self.similarity_memory.stop()