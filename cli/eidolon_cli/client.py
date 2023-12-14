import json
import os.path
import re
from typing import Optional, List
from urllib.parse import urljoin

import aiohttp
import httpx

from eidolon_cli.schema import Schema, AgentProgram


class EidolonClient:
    server_location: Optional[str] = None
    timeout = httpx.Timeout(5.0, read=600.0)
    agent_programs = None

    async def set_server_location(self, server_location: str):
        self.server_location = server_location
        async with aiohttp.ClientSession() as session:
            async with session.get(urljoin(self.server_location, "openapi.json")) as resp:
                openapi_json = await resp.json()

        programs_re = "^/agents/([^/]+)/programs/([^/]+)$"
        processes_re = "^/agents/([^/]+)/processes/{process_id}/actions/([^/]+)$"
        paths: List[str] = openapi_json["paths"]
        # iterate over paths and find the ones that match the regex returning a list of tuples of the form (agent, program)
        agent_programs = []
        for path in paths:
            programs_results = re.search(programs_re, path)
            processes_results = re.search(processes_re, path)
            if programs_results:
                name = programs_results.group(1)
                program = programs_results.group(2)
                is_program = True
            elif processes_results:
                name = processes_results.group(1)
                program = processes_results.group(2)
                is_program = False
            else:
                continue
            agent_obj = openapi_json["paths"][path]["post"]

            description = agent_obj["description"] if "description" in agent_obj else ""
            if "requestBody" not in agent_obj:
                schema = Schema(is_multipart=False, schema={"properties": {}, "type": "object", "required": []})
            else:
                schema = Schema.from_json_schema(openapi_json, agent_obj["requestBody"]["content"])

            agent_programs.append(
                AgentProgram(
                    name=name,
                    description=description,
                    program=program,
                    schema=schema,
                    is_program=is_program
                )
            )

        self.agent_programs = agent_programs

    async def get_client(self, agent_str: str):
        user_agent, user_program = agent_str.strip().split("/")

        for agent in self.agent_programs:
            if agent.name == user_agent and agent.program == user_program:
                return agent
        return None

    async def send_request(self, agent, user_input, process_id):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if agent.is_program:
                agent_url = f"/agents/{agent.name}/programs/{agent.program}"
            else:
                agent_url = f"/agents/{agent.name}/processes/{process_id}/actions/{agent.program}"
            print("url", urljoin(self.server_location, agent_url))
            if agent.schema.is_multipart:
                files = None
                data = {}

                def read_file(path: str):
                    with open(path, "rb") as f:
                        return f.read()

                for k, v in agent.schema.schema["properties"].items():
                    if v.get("type") == "string" and v.get("format") == "binary":
                        files = {k: (os.path.basename(user_input[k][0]), read_file(user_input[k][0]))}
                    elif v.get("type") == "array" and v["items"].get("type") == "string" and v["items"].get("format") == "binary":
                        files = [(k, read_file(file)) for file in user_input[k]]
                    else:
                        data[k] = json.dumps(user_input[k])
                for file_name, file in files:
                    print("file", file_name, len(file))
                request = {
                    "url": urljoin(self.server_location, agent_url),
                    "data": data
                }
                if files:
                    request["files"] = files
            else:
                request = {
                    "url": urljoin(self.server_location, agent_url),
                    "json": user_input
                }
            response = await client.post(**request)
            return response.status_code, response.json()