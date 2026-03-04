from pydantic import BaseModel


def serialize_response(response: BaseModel) -> dict:
    """Serialize a response model, excluding None fields."""
    return response.model_dump(by_alias=True, exclude_none=True)
