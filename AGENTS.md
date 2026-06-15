# AGENTS.md

## Project Purpose

This repository is an engineering drawing crop workbench with a standalone OCR test pipeline. The web UI currently ends at producing page snapshots, crop images, and box coordinate metadata; OCR remains a command-line workflow.

## Architecture

- `app.py`: FastAPI routes, PDF rendering, job output, and cropping.
- `frontend/`: React + Vite source code.
- `static/`: generated React production build served by FastAPI.
- `test-ED/`: source PDFs available to the UI.
- `output/`: generated job folders; do not commit.
- `src/ocr.py`: standalone GLM-OCR and GD symbol-classifier test runner.
- `src/symbol-classifierdata/`: runtime GD classifier helper and checkpoint.
- `tests/`: API and crop behavior tests.

## Coordinate Contract

Frontend boxes use the original pixel coordinates of the preview PNG rendered at `PREVIEW_SCALE = 2.0`. Do not change the preview render scale or send CSS/display coordinates without updating both frontend and backend behavior.

## Development Rules

- Keep the implementation simple and dependency-light.
- Make surgical changes; do not refactor unrelated UI or API behavior.
- Preserve box order. Deleting a box must renumber later boxes without reordering them.
- Keep tool behavior distinct: crop mode creates boxes; select mode moves and resizes existing boxes.
- Moving and resizing must clamp boxes to the preview image bounds.
- Validate changes with `.\.venv\Scripts\pytest.exe`.
- After frontend changes, run `npm run build` from `frontend/` and verify the generated app in a browser.
- Use `uv pip install --python .\.venv\Scripts\python.exe ...` for dependencies.
- Never commit files generated under `output/`.
- Keep OCR output as one `ocr_results.json` file inside the selected job folder.
- Keep OCR testing independent from the web UI until OCR integration is explicitly requested.
- Do not manually edit generated files under `static/`; edit React source under `frontend/src/`.

## Run Locally

```powershell
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
cd frontend
npm install
npm run build
cd ..
.\.venv\Scripts\uvicorn.exe app:app --reload
```

## Run OCR Test

```powershell
.\.venv\Scripts\python.exe .\src\ocr.py
```
