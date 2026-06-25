"""Source chat streaming service.

Extracted from api/routers/source_chat.py so the graph-invocation and SSE
event-building logic can be independently tested and reused.
"""

import asyncio
import json
from typing import AsyncGenerator, Optional

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger

from open_notebook.graphs.source_chat import source_chat_graph as source_chat_graph


async def stream_source_chat_response(
    session_id: str, source_id: str, message: str, model_override: Optional[str] = None
) -> AsyncGenerator[str, None]:
    """Stream the source chat response as Server-Sent Events."""
    try:
        # Use sync get_state() in a thread since SqliteSaver doesn't support async
        current_state = await asyncio.to_thread(
            source_chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": session_id}),
        )

        state_values = current_state.values if current_state else {}
        state_values["messages"] = state_values.get("messages", [])
        state_values["source_id"] = source_id
        state_values["model_override"] = model_override

        user_message = HumanMessage(content=message)
        state_values["messages"].append(user_message)

        user_event = {"type": "user_message", "content": message, "timestamp": None}
        yield f"data: {json.dumps(user_event)}\n\n"

        result = source_chat_graph.invoke(
            input=state_values,  # type: ignore[arg-type]
            config=RunnableConfig(
                configurable={"thread_id": session_id, "model_id": model_override}
            ),
        )

        if "messages" in result:
            for msg in result["messages"]:
                if hasattr(msg, "type") and msg.type == "ai":
                    ai_event = {
                        "type": "ai_message",
                        "content": msg.content if hasattr(msg, "content") else str(msg),
                        "timestamp": None,
                    }
                    yield f"data: {json.dumps(ai_event)}\n\n"

        if "context_indicators" in result:
            context_event = {
                "type": "context_indicators",
                "data": result["context_indicators"],
            }
            yield f"data: {json.dumps(context_event)}\n\n"

        completion_event = {"type": "complete"}
        yield f"data: {json.dumps(completion_event)}\n\n"

    except Exception as e:
        from open_notebook.utils.error_classifier import classify_error

        _, user_message = classify_error(e)
        logger.error(f"Error in source chat streaming: {str(e)}")
        error_event = {"type": "error", "message": user_message}
        yield f"data: {json.dumps(error_event)}\n\n"
