from typing import Any, List, Optional

from api.models import AssetModel, SourceResponse


def source_to_response(
    source: Any,
    embedded_chunks: int,
    *,
    include_asset: bool = True,
    command_id: Optional[str] = None,
    status: Optional[str] = None,
    processing_info: Optional[dict] = None,
    file_available: Optional[bool] = None,
    notebooks: Optional[List[str]] = None,
    has_sections: bool = False,
    sections_count: int = 0,
) -> SourceResponse:
    """Build a SourceResponse from a Source domain object.

    Pass include_asset=False for async-create responses where the asset
    has not been processed yet and should not be exposed.
    Pass has_sections/sections_count from a pre-fetched count query to signal
    whether chaptering data is available (avoids loading full section trees here).
    """
    asset = None
    if include_asset and source.asset:
        asset = AssetModel(
            file_path=source.asset.file_path,
            url=source.asset.url,
        )
    return SourceResponse(
        id=source.id or "",
        title=source.title,
        topics=source.topics or [],
        asset=asset,
        full_text=source.full_text if include_asset else None,
        embedded=embedded_chunks > 0,
        embedded_chunks=embedded_chunks,
        created=str(source.created),
        updated=str(source.updated),
        command_id=command_id,
        status=status,
        processing_info=processing_info,
        file_available=file_available,
        notebooks=notebooks,
        has_sections=has_sections,
        sections_count=sections_count,
    )
