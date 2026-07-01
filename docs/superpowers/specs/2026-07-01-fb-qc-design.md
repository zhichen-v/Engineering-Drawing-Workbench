# FB_QC 前後端整合設計

## 目標

在既有 MIP、QC Excel 輸出流程中加入第三種 `FB_QC` 格式。FB_QC 使用 `template/FB_QC.XLSM`，保留與 QC 相同的 OCR 欄位轉換、允差規則及 GD&T 符號，輸出至 `<job>/excel-output/FB_QC/FB_QC_filled.xlsm`。

## 實作方式

- 前端格式切換加入 `FB_QC`，沿用現有產生、快取、預覽與下載流程。
- 後端 `ExcelRequest` 接受 `FB_QC`，並將格式交給既有 Excel 執行入口。
- `fill_QC.py` 同時支援 `QC` 與 `FB_QC`，共用 OCR 解析及填表程式，只依格式選擇範本、版面與輸出檔名。
- `FB_QC_LAYOUT` 使用 `OGQC` 工作表，資料從第 8 列開始，共 11 個範本資料列，第 19 列起為既有外觀檢查區；資料超過 11 筆時，沿用既有插列行為將後段內容下移。
- 將 QC 範本的「選項」工作表複製到 FB_QC 範本，讓既有 GD&T 符號插入邏輯直接重用。

## 資料流與輸出

前端送出 `{ "format": "FB_QC" }` 至既有 `/api/jobs/{job_id}/excel`。後端確認 OCR 結果存在後執行 `fill_QC.py --format FB_QC`，回傳：

- Excel：`/output/{job_id}/excel-output/FB_QC/FB_QC_filled.xlsm`
- 預覽：`/output/{job_id}/excel-output/FB_QC/FB_QC_snapshot.png`
- 預覽工作表名稱：`OGQC`

既有 MIP 與 QC 的路徑、檔名及行為不變。

## 錯誤處理

沿用現有 API 行為：缺少 OCR 結果回傳 400；範本、Excel COM 或快照產生失敗回傳 500。未知格式由 Pydantic 驗證拒絕，不新增額外分支。

## 驗證

先加入會失敗的 API 測試，確認 FB_QC 格式、執行參數及回傳 URL；再加入最小實作使測試通過。最後執行完整 pytest、前端 production build，並在瀏覽器確認第三個格式選項可操作。
