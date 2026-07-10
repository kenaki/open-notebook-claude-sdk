"""Surreal-commands integration for Open Notebook"""

from .block_commands import build_blocks_command
from .chat_commands import chat_completion_command
from .embedding_commands import (
    embed_insight_command,
    embed_note_command,
    embed_source_command,
    rebuild_embeddings_command,
)
from .example_commands import analyze_data_command, process_text_command
from .illustrate_commands import illustrate_message_command
from .podcast_commands import generate_podcast_command
from .section_commands import backfill_sections_command, build_sections_command
from .source_commands import process_source_command
from .study_memory_commands import (
    embed_annotation_command,
    mirror_chat_exchange_command,
)
from .summary_commands import generate_source_abstract, summarize_section
from .verify_commands import verify_clean_section, verify_clean_source

__all__ = [
    # Embedding commands
    "embed_note_command",
    "embed_insight_command",
    "embed_source_command",
    "rebuild_embeddings_command",
    # Section / chaptering commands
    "build_sections_command",
    "backfill_sections_command",
    # PDF block substrate ingestion command
    "build_blocks_command",
    # Vision verify-clean commands
    "verify_clean_section",
    "verify_clean_source",
    # Per-section summaries + doc abstract commands
    "summarize_section",
    "generate_source_abstract",
    # Chat illustration enrichment command
    "illustrate_message_command",
    # Study-memory substrate commands
    "embed_annotation_command",
    "mirror_chat_exchange_command",
    # Other commands
    "chat_completion_command",
    "generate_podcast_command",
    "process_source_command",
    "process_text_command",
    "analyze_data_command",
]
