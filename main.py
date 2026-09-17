import os
import uvicorn
from app.config import settings
from app.main import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", settings.PORT))
    uvicorn.run("app.main:app", host=settings.HOST, port=port, reload=False)
