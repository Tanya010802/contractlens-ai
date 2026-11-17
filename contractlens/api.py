from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .compare import SpecError, compare
from .suggestions import model_enabled, suggest


class ComparisonInput(BaseModel):
    before: dict
    after: dict


class SuggestionInput(ComparisonInput):
    finding_id: str


app = FastAPI(title="ContractLens AI")


def run_comparison(data):
    try:
        return compare(data.before, data.after)
    except (SpecError, RecursionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/config")
def config():
    return {"ai_available": model_enabled()}


@app.post("/api/compare")
def compare_specs(data: ComparisonInput):
    return run_comparison(data)


@app.post("/api/suggestions")
def suggest_tests(data: SuggestionInput):
    if not model_enabled():
        raise HTTPException(status_code=503, detail="AI generation is disabled on this server.")
    finding = next((item for item in run_comparison(data)["findings"] if item["id"] == data.finding_id), None)
    if finding is None:
        raise HTTPException(status_code=404, detail="The finding is missing from this comparison.")
    try:
        return {"finding_id": finding["id"], **suggest(finding)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


root = Path(__file__).resolve().parent.parent
app.mount("/examples", StaticFiles(directory=root / "examples"), name="examples")
bundle = root / "frontend" / "dist"
if (bundle / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=bundle / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(bundle / "index.html")
