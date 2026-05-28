from pydantic import BaseModel


class NormalizedLandmark(BaseModel):
    x: float
    y: float
    z: float
