from app import app
import uvicorn
import os

if __name__ == "__main__":
    # uvicorn.run('main:app', host = '0.0.0.0', port = 10000, reload = True)
    port = int(os.environ.get("PORT", 8000))  # Azure sets this automatically
    uvicorn.run(app, host="0.0.0.0",port=port)


