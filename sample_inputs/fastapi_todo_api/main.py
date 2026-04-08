from fastapi import FastAPI

app = FastAPI(title="Sample Todo API")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/todos")
def list_todos():
    return [
        {"id": 1, "title": "Ship demo", "done": False},
        {"id": 2, "title": "Watch agent debate", "done": True},
    ]
