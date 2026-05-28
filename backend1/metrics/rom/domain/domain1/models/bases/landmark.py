from pydantic import BaseModel
from typing import Optional


class Landmark(BaseModel):
    x: float
    y: float
    z: float
    visibility: float


class NormalizedLandmark(BaseModel):
    x: float
    y: float
    z: float
