# ED Crop Workbench

從 `test-ED/` 載入 PDF，在 React 前端預覽工程圖並建立裁切範圍。後端會在 `output/` 建立以日期時間與隨機序號命名的工作資料夾，儲存完整頁面 snapshot、框選座標 JSON 與裁切圖片。

## 安裝與建置

```powershell
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
2. 使用「框選裁切區域」或快捷鍵 `C`，在圖面上拖曳建立 box。
3. 使用「選取／調整」或快捷鍵 `V`，拖曳 box 移動位置，或拖曳四角控制點調整大小。
4. 使用頂部橫框調整所有 box 的線寬、透明度與顏色。
5. 「儲存標註資料」會輸出 snapshot 與 `boxes.json`。
6. 「執行裁切」會額外輸出 `crop_001.png`、`crop_002.png` 等圖片。

## 驗證

```powershell
.\.venv\Scripts\pytest.exe
cd frontend
npm run build
```
