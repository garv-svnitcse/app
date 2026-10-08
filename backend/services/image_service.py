import asyncio
import logging
import os
import re
import uuid

import cloudinary.uploader
from fastapi import HTTPException, UploadFile

logger = logging.getLogger("wavygo")

MAX_SIZE = 10 * 1024 * 1024  # 10MB (Cloudinary's free plan limit for non-video files)

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | {
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "zip",
}


def _safe_name(filename: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(filename or "file"))
    return name[:80] or "file"


async def upload_file(file: UploadFile) -> dict:
    original_name = os.path.basename(file.filename or "file")
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Files of type .{ext or 'unknown'} are not allowed")

    contents = await file.read()
    if not contents:
        raise HTTPException(400, "File is empty")
    if len(contents) > MAX_SIZE:
        raise HTTPException(400, "File too large (max 10MB)")

    is_image = ext in IMAGE_EXTENSIONS
    resource_type = "image" if is_image else "raw"

    options = {
    "folder": "wavygo-chat",
    "resource_type": resource_type,
    "type": "upload",
    }
    if not is_image:
        options["public_id"] = f"{uuid.uuid4().hex[:12]}_{_safe_name(original_name)}"
    
    try:
        result = await asyncio.to_thread(cloudinary.uploader.upload, contents, **options)
    except Exception as e:
        logger.exception("Cloudinary upload failed")
        raise HTTPException(500, f"Upload failed: {e}")

    return {
        "url": result["secure_url"],
        "public_id": result["public_id"],
        "resource_type": resource_type,
        "name": original_name,
        "size": len(contents),
        "content_type": file.content_type or "",
        "is_image": is_image,
    }


async def delete_file(public_id: str, resource_type: str = "image") -> None:
    """Delete a file from Cloudinary. Never raises, so a Cloudinary problem
    doesn't block deleting the message itself."""
    try:
        await asyncio.to_thread(
            cloudinary.uploader.destroy,
            public_id,
            resource_type=resource_type,
            invalidate=True,
        )
    except Exception:
        logger.exception("Cloudinary delete failed for %s", public_id)