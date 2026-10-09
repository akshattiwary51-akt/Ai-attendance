"""Safe image loading for uploads / camera input."""
from __future__ import annotations

from PIL import Image, UnidentifiedImageError

from src.config.settings import get_settings
from src.utils.errors import ValidationError


def load_image(file_like) -> Image.Image:
    """Validate size, decode, convert to RGB and bound the longest side."""
    s = get_settings()
    size = getattr(file_like, "size", None)
    if size is not None and size > s.max_upload_mb * 1024 * 1024:
        raise ValidationError("upload too large", user_message=f"Image is larger than {s.max_upload_mb} MB.")
    try:
        img = Image.open(file_like)
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError("bad image", user_message="That file is not a valid image.") from exc
    img = img.convert("RGB")
    if max(img.size) > s.max_image_side:
        img.thumbnail((s.max_image_side, s.max_image_side))
    return img
