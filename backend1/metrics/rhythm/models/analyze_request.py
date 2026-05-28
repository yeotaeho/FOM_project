from pydantic import BaseModel, Field


class AnalyzeFormParams(BaseModel):
    """Swagger 문서용; 실제 엔드포인트는 Form() 파라미터."""
    user_video: str = Field(..., description="사용자 댄스 영상 파일명")
