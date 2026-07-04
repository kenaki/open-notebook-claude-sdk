import asyncio
import concurrent.futures
from typing import Awaitable, Callable, TypeVar

from langchain_core.runnables import RunnableConfig
from loguru import logger

_T = TypeVar("_T")


def run_async_in_node(make_coro: Callable[[], Awaitable[_T]]) -> _T:
    """Run an async coroutine to completion from inside a **sync** LangGraph node.

    LangGraph invokes node functions synchronously, but model provisioning and
    context building are ``async``. This bridges the two without deadlocking,
    reproducing exactly the branch the chat / source_chat nodes have always used:

    - **No running loop** (the worker path — ``graph.invoke`` runs inside an
      ``asyncio.to_thread`` worker thread that has no loop): run the coroutine
      directly on this thread via ``asyncio.run``.
    - **A loop is already running** (node driven from async code on this
      thread): ``run_until_complete`` cannot be nested inside it, so run the
      coroutine in a *fresh* event loop on a separate ``ThreadPoolExecutor``
      thread and block for the result.

    ``make_coro`` is a **zero-arg factory** (e.g. ``lambda: _generate(...)``),
    not a coroutine object: each branch calls it to obtain a *fresh* coroutine,
    exactly as the original inline bridge re-invoked the async function per
    branch. Passing a bare coroutine will not work.

    ⚠️ Timing-sensitive: get this branch wrong and chat can DEADLOCK. Keep the
    running-loop -> separate-thread / no-loop -> ``asyncio.run`` split intact
    (see ``open_notebook/graphs/CLAUDE.md`` "Async loop gymnastics").
    """

    def run_in_new_loop() -> _T:
        """Run the async function in a new event loop"""
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            return new_loop.run_until_complete(make_coro())
        finally:
            new_loop.close()
            asyncio.set_event_loop(None)

    try:
        # Try to get the current event loop
        asyncio.get_running_loop()
        # If we're in an event loop, run in a thread with a new loop
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_in_new_loop)
            return future.result()
    except RuntimeError:
        # No event loop running, safe to use asyncio.run()
        return asyncio.run(make_coro())


async def get_session_message_count(graph, session_id: str) -> int:
    """Get message count from LangGraph state, returns 0 on error."""
    try:
        # Use sync get_state() in a thread (SqliteSaver doesn't support async)
        thread_state = await asyncio.to_thread(
            graph.get_state,
            config=RunnableConfig(configurable={"thread_id": session_id}),
        )
        if (
            thread_state
            and thread_state.values
            and "messages" in thread_state.values
        ):
            return len(thread_state.values["messages"])
    except Exception as e:
        logger.warning(f"Could not fetch message count for session {session_id}: {e}")
    return 0
