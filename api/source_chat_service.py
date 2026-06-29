"""Source chat service.

The ``stream_source_chat_response`` function that previously lived here was
retired in A3 (background-jobs plan). Source chat is now executed as a
``chat_completion`` background job via ``CommandService.submit_command_job``
in ``api/routers/source_chat.py``. The graph invocation runs in the worker
(``commands/chat_commands.py``) and persists messages to the LangGraph SQLite
checkpoint, which the ``GET /sources/{id}/chat/sessions/{sid}`` endpoint reads.
"""
