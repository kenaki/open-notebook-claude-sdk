from typing import Any, Dict, List, Union


def _unwrap(resp: Union[Dict[str, Any], List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Return the dict payload from a repo response.

    repo_* calls return either the record dict directly or a single-element list.
    Raises IndexError on empty list (matches prior implicit behavior).
    """
    if isinstance(resp, dict):
        return resp
    return resp[0]


def _as_list(resp: Any) -> List[Any]:
    """Normalise a repo response to a list."""
    if isinstance(resp, list):
        return resp
    return [resp]
