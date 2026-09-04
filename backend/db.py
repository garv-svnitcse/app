from __future__ import annotations
"""Shared MongoDB client + Pydantic ObjectId helpers."""
import os
from typing import Annotated, Any, Optional
from bson import ObjectId
# pyrefly: ignore [missing-import]
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BeforeValidator, BaseModel, ConfigDict, Field
from datetime import datetime, timezone


def _validate_object_id(v: Any) -> str:
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, str):
        if ObjectId.is_valid(v):
            return v
        raise ValueError("Invalid ObjectId")
    raise ValueError("ObjectId must be a string or bson.ObjectId")


PyObjectId = Annotated[str, BeforeValidator(_validate_object_id)]


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: Optional[PyObjectId] = Field(default=None, alias="_id")

    @classmethod
    def from_mongo(cls, doc: dict | None):
        if doc is None:
            return None
        doc = dict(doc)
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        return cls.model_validate(doc)

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude_none=True)
        if "_id" in data and isinstance(data["_id"], str) and ObjectId.is_valid(data["_id"]):
            data["_id"] = ObjectId(data["_id"])
        elif "_id" in data and data["_id"] is None:
            data.pop("_id")
        return data


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso() -> str:
    return utc_now().isoformat()


try:
    import certifi
    ca_file = certifi.where()
except Exception:
    ca_file = None

_client: AsyncIOMotorClient | None = None
_db = None


def get_db():
    global _client, _db
    if _db is None:
        url = (
            os.environ.get("MONGO_URL")
            or os.environ.get("MONGO_URI")
            or os.environ.get("MONGODB_URI")
            or os.environ.get("MONGODB_URL")
            or os.environ.get("DATABASE_URL")
            or "mongodb://localhost:27017"
        ).strip()
        kwargs = {"serverSelectionTimeoutMS": 10000}
        if "mongodb+srv://" in url or "tls=true" in url or "ssl=true" in url:
            if ca_file:
                kwargs["tlsCAFile"] = ca_file
            kwargs["tlsAllowInvalidCertificates"] = True
        _client = AsyncIOMotorClient(url, **kwargs)

        db_name = os.environ.get("DB_NAME") or os.environ.get("DATABASE_NAME")
        if db_name and db_name.strip():
            _db = _client[db_name.strip()]
        else:
            try:
                _db = _client.get_default_database()
                if _db is None:
                    _db = _client["wavygo_db"]
            except Exception:
                _db = _client["wavygo_db"]
    return _db


def close_db():
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None
