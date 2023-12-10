import asyncio
import os
from contextlib import asynccontextmanager, contextmanager
from typing import Iterable

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient

from eidos.memory.agent_memory import VectorMemory
from eidos.memory.local_file_memory import LocalFileMemory, LocalFileMemoryConfig
from eidos.memory.mongo_symbolic_memory import MongoSymbolicMemory
from eidos.memory.noop_memory import NoopVectorStore
from eidos.system.agent_http_server import start_os
from eidos.system.reference_model import Reference
from eidos.system.resources import AgentResource
from eidos.system.resources_base import Resource, Metadata
from eidos.util.class_utils import fqn


@pytest.fixture(scope='module')
def app_builder(machine_manager):
    def fn(resources: Iterable[Resource]):
        @asynccontextmanager
        async def manage_lifecycle(_app: FastAPI):
            async with machine_manager() as _machine:
                async with start_os(_app, [_machine, *resources] if _machine else resources):
                    yield

        return FastAPI(lifespan=manage_lifecycle)
    return fn


@pytest.fixture(scope='module')
def client_builder(app_builder):
    def fn(*agents):
        resources = [
            a if isinstance(a, Resource) else AgentResource(
                apiVersion="eidolon/v1",
                implementation=fqn(a),
                metadata=Metadata(name=a.__name__)
            )
            for a in agents
        ]
        return TestClient(app_builder(resources))
    return fn


@pytest.fixture(scope='module')
def machine_manager(file_memory, symbolic_memory, similarity_memory):
    @asynccontextmanager
    async def fn():
        async with symbolic_memory() as sm:
            yield Resource(
                apiVersion="eidolon/v1",
                kind="Machine",
                spec=dict(
                    symbolic_memory=sm,
                    file_memory=file_memory,
                    similarity_memory=similarity_memory,
                )
            )

    return fn


@pytest.fixture(scope='module')
def symbolic_memory(module_identifier):
    @asynccontextmanager
    async def fn():
        # Setup unique database for test suite
        database_name = f"test_db_{module_identifier}_{ObjectId()}"  # Unique name for test database
        ref = Reference(implementation=fqn(MongoSymbolicMemory), spec=dict(mongo_database_name=database_name))
        memory = ref.instantiate()
        memory.start()
        yield ref
        memory.stop()
        # Teardown: drop the test database
        connection_string = os.getenv('MONGO_CONNECTION_STRING')
        client = AsyncIOMotorClient(connection_string)
        await client.drop_database(database_name)
        client.close()

    return fn


@pytest.fixture(scope='module')
def file_memory(tmp_path_factory, module_identifier):
    storage_loc = tmp_path_factory.mktemp(f"file_memory_{module_identifier}")
    spec = LocalFileMemoryConfig(root_dir=str(storage_loc))
    return Reference[LocalFileMemory](spec=spec)


@pytest.fixture(scope='module')
def similarity_memory():
    return Reference[VectorMemory](spec=dict(
        vector_store=dict(implementation=fqn(NoopVectorStore)),
    ))


@pytest.fixture(scope='module', autouse=True)
def module_identifier(request):
    return request.node.name.replace('.', '_')
