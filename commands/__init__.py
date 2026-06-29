"""Surreal-commands integration for Open Notebook"""

from .chat_commands import chat_completion_command
from .embedding_commands import (
    embed_insight_command,
    embed_note_command,
    embed_source_command,
    rebuild_embeddings_command,
)
from .example_commands import analyze_data_command, process_text_command
from .podcast_commands import generate_podcast_command
from .section_commands import backfill_sections_command, build_sections_command
from .source_commands import process_source_command

__all__ = [
    # Embedding commands
    "embed_note_command",
    "embed_insight_command",
    "embed_source_command",
    "rebuild_embeddings_command",
    # Section / chaptering commands
    "build_sections_command",
    "backfill_sections_command",
    # Other commands
    "chat_completion_command",
    "generate_podcast_command",
    "process_source_command",
    "process_text_command",
    "analyze_data_command",
]
