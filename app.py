import os, json

from pathlib import Path
from typing import List
from openai import AsyncAssistantEventHandler, AsyncOpenAI, OpenAI

import chainlit as cl
from chainlit.config import config
from chainlit.element import Element
from literalai.helper import utc_now

from config import FUNCTION_MAP, ASSISTANT_TOOLS


async_openai_client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
sync_openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

assistant = sync_openai_client.beta.assistants.create(
    name="Market Visualization Expert",
    instructions="""
You are a Market Researcher

Your task is to help the user visualize market research.
You can retrieve data from google maps. You can plot this data on a map with Folium.
""",
    tools=[
        {"type": "file_search"},
        *ASSISTANT_TOOLS,
    ],
    model="gpt-4o",
)

config.ui.name = assistant.name


def _stop_all_runs(thread_id: str):
    runs_result = sync_openai_client.beta.threads.runs.list(thread_id, limit=100)
    while runs_result.has_more:
        for run in runs_result.data:
            sync_openai_client.beta.threads.runs.cancel(
                thread_id=thread_id, run_id=run.id
            )
        runs_result = sync_openai_client.beta.threads.runs.list(thread_id, limit=100)


FILLER_MESSAGE_TEXT = "Thinking..."


class EventHandler(AsyncAssistantEventHandler):

    def __init__(self, assistant_name: str, thread_id: str) -> None:
        super().__init__()
        self.current_message: cl.Message | None = None
        self.current_tool_call = None
        self.assistant_name = assistant_name
        self.thread_id = thread_id

    async def on_event(self, event) -> None:
        if event.event == "thread.run.created":
            self.current_message = cl.Message(content=FILLER_MESSAGE_TEXT)
            await self.current_message.send()
        if event.event == "thread.run.requires_action":
            run_id = event.data.id
            await self.handle_requires_action(event.data, run_id)

    async def handle_requires_action(self, data, run_id) -> None:
        tool_outputs = []
        for tool in data.required_action.submit_tool_outputs.tool_calls:
            function_name = tool.function.name
            function_args = json.loads(tool.function.arguments)

            result = FUNCTION_MAP.get(function_name)(**function_args)
            tool_outputs.append({"tool_call_id": tool.id, "output": json.dumps(result)})
        await self.submit_tool_outputs(tool_outputs, run_id)

    async def submit_tool_outputs(self, tool_outputs, run_id) -> None:
        async with async_openai_client.beta.threads.runs.submit_tool_outputs_stream(
            thread_id=self.thread_id, run_id=run_id, tool_outputs=tool_outputs
        ) as stream:
            if self.current_message is None:
                self.current_message = cl.Message(content="")
            else:
                self.current_message.content = ""
                await self.current_message.update()
            async for text in stream.text_deltas:
                await self.current_message.stream_token(text)
            await self.current_message.update()

    async def on_text_created(self, text) -> None:
        if self.current_message is None:
            self.current_message = cl.Message(content="")
            await self.current_message.send()
        elif self.current_message.content == FILLER_MESSAGE_TEXT:
            self.current_message.content = ""
            await self.current_message.update()

    async def on_text_delta(self, delta, snapshot):
        await self.current_message.stream_token(delta.value)

    async def on_text_done(self, text):
        await self.current_message.update()

    async def on_image_file_done(self, image_file):
        image_id = image_file.file_id
        response = await async_openai_client.files.with_raw_response.content(image_id)
        image_element = cl.Image(
            name=image_id, content=response.content, display="inline", size="large"
        )
        if not self.current_message.elements:
            self.current_message.elements = []
        self.current_message.elements.append(image_element)
        await self.current_message.update()


async def upload_files(files: List[Element]):
    file_ids = []
    for file in files:
        uploaded_file = await async_openai_client.files.create(
            file=Path(file.path), purpose="assistants"
        )
        file_ids.append(uploaded_file.id)
    return file_ids


async def process_files(files: List[Element]):
    # Upload files if any and get file_ids
    file_ids = []
    if len(files) > 0:
        file_ids = await upload_files(files)

    return [
        {
            "file_id": file_id,
            "tools": [{"type": "file_search"}],
        }
        for file_id in file_ids
    ]


@cl.on_chat_start
async def start_chat():
    # Create a Thread
    thread = await async_openai_client.beta.threads.create()
    # Store thread ID in user session for later use
    cl.user_session.set("thread_id", thread.id)
    await cl.Message(content="Hi, How can I help you today?").send()


@cl.action_callback("starter_action")
async def on_action(action):
    await main(cl.Message(content=action.payload["value"]))
    await action.remove()


@cl.on_chat_end
async def on_chat_end():
    thread_id = cl.user_session.get("thread_id")
    _stop_all_runs(thread_id)


@cl.on_message
async def main(message: cl.Message):
    thread_id = cl.user_session.get("thread_id")

    attachments = await process_files(message.elements)
    if message.content == "":
        message.content += "The user uploaded files."

    # Add a Message to the Thread
    oai_message = await async_openai_client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=message.content,
        attachments=attachments,
    )

    # Create and Stream a Run
    async with async_openai_client.beta.threads.runs.stream(
        thread_id=thread_id,
        assistant_id=assistant.id,
        event_handler=EventHandler(assistant_name=assistant.name, thread_id=thread_id),
    ) as stream:
        await stream.until_done()


@cl.on_stop
async def on_stop():
    thread_id = cl.user_session.get("thread_id")
    _stop_all_runs(thread_id)
