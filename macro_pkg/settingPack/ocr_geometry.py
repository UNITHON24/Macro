from __future__ import annotations


def restore_polygon(polygon, scale: float):
    """Map OCR coordinates from a resized image back to the capture space."""
    if scale <= 0:
        raise ValueError("OCR scale must be positive")
    return [[float(point[0]) / scale, float(point[1]) / scale] for point in polygon]
