# ED Crop Workbench

從 `test-ED/` 載入 PDF，在 React 前端預覽工程圖並建立裁切範圍。後端會在 `output/` 建立以日期時間與隨機序號命名的工作資料夾，儲存完整頁面 snapshot、框選座標 JSON 與裁切圖片。

## 安裝與建置

```powershell
git clone https://github.com/zhichen-v/Engineering-Drawing-Workbench.git
cd .\Engineering-Drawing-Workbench
uv venv --python 3.12
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
cd frontend
npm install
npm run build
cd ..
```

## 啟動

```powershell
.\.venv\Scripts\uvicorn.exe app:app --reload
```

開啟 `http://127.0.0.1:8000`。

修改 React 前端後需重新執行 `cd frontend; npm run build`。開發期間也可以在 FastAPI 運行時使用 `npm run dev`。

## 操作

1. 從左側選擇 PDF 與頁面。
2. 使用「框選裁切區域」或快捷鍵 `C`，在圖面空白處拖曳建立 box；建立後可直接移動或調整四角。
3. 使用「選取／調整」或快捷鍵 `V`，拖曳 box 移動位置，或拖曳四角控制點調整大小。
4. 滾動滑鼠可縮放圖面；在選取模式拖曳圖面空白處可平移，工作區外框大小維持不變。
5. 使用頂部橫框調整所有 box 的線寬、透明度與顏色。
6. 同一份 PDF 的所有頁面共用一個 output job；切換頁面會保留各頁 boxes，編號會跨頁延續。
7. 「儲存標註資料」會輸出各頁 snapshot、`boxes.json` 與 `crop_001.png`、`crop_002.png` 等圖片。
8. box 新增、移動、縮放或刪除後，必須先重新儲存標註資料，才能執行辨識。

## 驗證

```powershell
.\.venv\Scripts\pytest.exe
cd frontend
npm run build
```

## OCR

網頁中的「執行辨識」只會使用最近一次「儲存標註資料」產生的 crop 與 `boxes.json`。box 有未儲存變動時，辨識按鈕會停用，儲存按鈕會顯示提示動畫。完成後可切換 OCR 標註顯示，並可使用「重新編輯」保留 boxes 返回標註模式。再次執行時，crop number、頁面與完整 box 資料皆未改變的結果會直接沿用，不會重複辨識。

命令列測試使用 `--test` 指定 `output/` 下的 job 資料夾。

`requirements.txt` 使用 CUDA 12.6 版 Torch，安裝後會以 NVIDIA GPU 執行。

執行：

```powershell
.\.venv\Scripts\python.exe .\src\ocr.py --test 20260615T062952040Z_59102-0SBG000_dd3c9b1a_page_001
```

GLM-OCR 模型預設只從本機 Hugging Face cache 載入。若本機沒有模型，才使用：

```powershell
.\.venv\Scripts\python.exe .\src\ocr.py --test <folder_name> --allow-model-download
```

結果只會寫入一個 JSON：

```text
output/<folder_name>/ocr_results.json
```

每筆結果包含 `crop_number`、原始 `box` 座標與 `ocr`。GD 符號辨識成功時，`ocr` 開頭會包含例如 `[GD_FLATNESS]` 的標記；直徑分類器辨識成功時會補上 `⌀`。

GD tag 由影像分類器判定。若符號被判為 `UNKNOWN`，系統會保留一般 OCR 文字，不會只根據 `0.02 A B C` 之類的文字排列猜測 GD 類型。

## Excel 輸出

MIP 會輸出至 `<job>/excel-output/MIP`：

```powershell
.\.venv\Scripts\python.exe .\src\excel-method\fill_MIP_all.py --job <output-folder>
```

QC 會輸出至 `<job>/excel-output/QC`：

```powershell
.\.venv\Scripts\python.exe .\src\excel-method\fill_QC.py --job <output-folder>
```

量測設備的預設判定包含：GD 使用 CMM、表面粗糙度使用 Surface Roughness Tester；半徑、倒角、直徑及角度符號使用 Profile Projector。
