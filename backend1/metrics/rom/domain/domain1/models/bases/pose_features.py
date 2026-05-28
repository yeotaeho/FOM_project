from pydantic import BaseModel


class BoneVector(BaseModel):
    """단위 방향 벡터 (코사인 유사도용) + 정규화 공간에서의 뼈 길이."""

    x: float
    y: float
    z: float
    magnitude: float
