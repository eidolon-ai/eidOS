import os
from typing import Any, Optional, AsyncIterable, Union, Dict, List

from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorClient
from pydantic import Field, BaseModel

from eidos.memory.agent_memory import SymbolicMemory
from eidos.system.reference_model import Specable


class MongoSymbolicMemoryConfig(BaseModel):
    mongo_connection_string: Optional[str] = Field(default=None, description="The connection string to the MongoDB instance.")
    mongo_database_name: str = Field(default=None, description="The name of the MongoDB database to use.")


class MongoSymbolicMemory(SymbolicMemory, Specable[MongoSymbolicMemoryConfig]):
    mongo_connection_string: Optional[str] = Field(default=None, description="The connection string to the MongoDB instance.")
    mongo_database_name: str = Field(default=None, description="The name of the MongoDB database to use.")
    database: AsyncIOMotorDatabase = None

    def __init__(self, spec: MongoSymbolicMemoryConfig):
        super().__init__(spec)
        self.mongo_connection_string = spec.mongo_connection_string
        self.mongo_database_name = spec.mongo_database_name

    async def count(self, symbol_collection: str, query: dict[str, Any]) -> int:
        return await self.database[symbol_collection].count_documents(query)

    def find(self, symbol_collection: str, query: dict[str, Any], projection: Union[List[str], Dict[str, int]] = None) -> AsyncIterable[dict[str, Any]]:
        return self.database[symbol_collection].find(query, projection = projection)

    async def find_one(self, symbol_collection: str, query: dict[str, Any]) -> Optional[dict[str, Any]]:
        return await self.database[symbol_collection].find_one(query)

    async def insert(self, symbol_collection: str, documents: list[dict[str, Any]]) -> None:
        return await self.database[symbol_collection].insert_many(documents)

    async def insert_one(self, symbol_collection: str, document: dict[str, Any]) -> None:
        return await self.database[symbol_collection].insert_one(document)

    async def update_many(self, symbol_collection: str, query: dict[str, Any], document: dict[str, Any]) -> None:
        return await self.database[symbol_collection].update_many(query, document)

    async def upsert_one(self, symbol_collection: str, document: dict[str, Any], query: dict[str, Any]) -> None:
        return await self.database[symbol_collection].update_one(query, document, upsert=True)

    async def delete(self, symbol_collection, query):
        return await self.database[symbol_collection].delete_many(query)

    def start(self):
        """
        Starts the memory implementation. Noop for this implementation.
        """
        if self.database is None:
            if self.mongo_connection_string is None:
                self.mongo_connection_string = os.getenv('MONGO_CONNECTION_STRING')
            if self.mongo_database_name is None:
                self.mongo_database_name = os.getenv('MONGO_DATABASE_NAME')

            client = AsyncIOMotorClient(self.mongo_connection_string)
            self.database = client.get_database(self.mongo_database_name)

    def stop(self):
        """
        Stops the memory implementation. Noop for this implementation.
        """
        if self.database is not None:
            self.database.client.close()
            self.database = None
