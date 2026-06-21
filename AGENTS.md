# AGENTS.md

## Project Purpose

This repository is an engineering drawing crop and OCR workbench. The web UI produces page snapshots, crop images, box coordinate metadata, and an OCR result overlay. OCR can also be run independently from the command line for testing.

## Architecture

- `app.py`: FastAPI routes, PDF rendering, job output, and cropping.
- `frontend/`: React + Vite source code.
- `static/`: generated React production build served by FastAPI.
- `test-ED/`: source PDFs available to the UI.
- `output/`: generated job folders; do not commit.
- `src/ocr.py`: GLM-OCR and GD symbol-classifier runtime plus CLI test runner.
- `src/symbol-classifierdata/`: runtime GD classifier helper and checkpoint.
- `src/excel-method/`: MIP/QC workbook parsing, template filling, and snapshot scripts.
- `tests/`: API and crop behavior tests.

## Coordinate Contract

Frontend boxes use the original pixel coordinates of the preview PNG rendered at `PREVIEW_SCALE = 2.0`. Do not change the preview render scale or send CSS/display coordinates without updating both frontend and backend behavior.

All pages from one loaded PDF share one output job. Box IDs are unique and sequential across the whole document, and each saved box includes its page number.

## Development Rules

- Keep the implementation simple and dependency-light.
- Make surgical changes; do not refactor unrelated UI or API behavior.
- Preserve box order. Deleting a box must renumber later boxes without reordering them.
- Preserve boxes when switching pages within the same document and keep their IDs continuous across pages.
- Keep tool behavior distinct: crop mode creates boxes; select mode moves and resizes existing boxes.
- Moving and resizing must clamp boxes to the preview image bounds.
- Validate changes with `.\.venv\Scripts\pytest.exe`.
- After frontend changes, run `npm run build` from `frontend/` and verify the generated app in a browser.
- Use `uv pip install --python .\.venv\Scripts\python.exe ...` for dependencies.
- Never commit files generated under `output/`.
- Keep OCR output as one `ocr_results.json` file inside the selected job folder.
- Reuse an existing OCR result when its crop number and complete saved box metadata are unchanged.
- Require saved crop and box data before OCR; unsaved box changes must not be recognized.
- Do not infer a GD type from value/datum text alone when the image classifier returns `UNKNOWN`; improve and validate the classifier with representative data instead.
- Use `src/excel-method/fill_MIP_all.py` for MIP output and `src/excel-method/fill_QC.py` for QC output.
- Keep MIP output under `<job>/excel-output/MIP` and QC output under `<job>/excel-output/QC`.
- Keep the CLI OCR test path available through `--test <output-folder>`.
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
.\.venv\Scripts\python.exe .\src\ocr.py --test <output-folder>
```

## Run Excel Output

```powershell
.\.venv\Scripts\python.exe .\src\excel-method\fill_MIP_all.py --job <output-folder>
.\.venv\Scripts\python.exe .\src\excel-method\fill_QC.py --job <output-folder>
```
