import { useEffect, useMemo, useRef, useState } from "react";

const EMPTY_IMAGE_SIZE = { width: 0, height: 0 };
const MIN_BOX_SIZE = 20;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 5;
const CROP_COORDINATE_SCALE = 2;
const PREVIEW_RENDER_SCALE = 4;
const BOX_COLORS = [
  { name: "琥珀", value: "#bd7519" },
  { name: "藍色", value: "#245a8d" },
  { name: "綠色", value: "#0f5b52" },
  { name: "紅色", value: "#a83a35" },
];
const RESIZE_HANDLES = [
  { name: "nw", x: (box) => box.x, y: (box) => box.y },
  { name: "ne", x: (box) => box.x + box.width, y: (box) => box.y },
  { name: "se", x: (box) => box.x + box.width, y: (box) => box.y + box.height },
  { name: "sw", x: (box) => box.x, y: (box) => box.y + box.height },
];

function createLoadId() {
  return new Date().toISOString().replace(/[-:.]/g, "");
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function normalizedBox(start, end) {
  return {
    x: Math.min(start.x, end.x),
    y: Math.min(start.y, end.y),
    width: Math.abs(end.x - start.x),
    height: Math.abs(end.y - start.y),
  };
}

function resizedBox(original, handle, point, imageSize) {
  let left = original.x;
  let top = original.y;
  let right = original.x + original.width;
  let bottom = original.y + original.height;

  if (handle.includes("w")) left = clamp(point.x, 0, right - MIN_BOX_SIZE);
  if (handle.includes("e")) right = clamp(point.x, left + MIN_BOX_SIZE, imageSize.width);
  if (handle.includes("n")) top = clamp(point.y, 0, bottom - MIN_BOX_SIZE);
  if (handle.includes("s")) bottom = clamp(point.y, top + MIN_BOX_SIZE, imageSize.height);

  return { x: left, y: top, width: right - left, height: bottom - top };
}

function SectionHeading({ step, eyebrow, title }) {
  return (
    <div className="section-heading">
      <span className="step-number">{step}</span>
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
      </div>
    </div>
  );
}

function SelectIcon() {
  return (
    <svg className="tool-svg" viewBox="0 0 28 28" aria-hidden="true">
      <path d="M5 3 21 16l-8 1 4 7-4 2-4-8-5 6Z" />
    </svg>
  );
}

function CropIcon() {
  return <span className="crop-icon" aria-hidden="true" />;
}

function ToolButton({ active, icon, title, description, shortcut, onClick }) {
  return (
    <button className={`tool-button ${active ? "active" : ""}`} onClick={onClick}>
      {icon}
      <div><strong>{title}</strong><small>{description}</small></div>
      <kbd>{shortcut}</kbd>
    </button>
  );
}

function AppearanceControls({ boxStyle, onChange }) {
  function updateStrokeWidth(event) {
    onChange({ ...boxStyle, strokeWidth: Number(event.currentTarget.value) });
  }

  function updateOpacity(event) {
    onChange({ ...boxStyle, opacity: Number(event.currentTarget.value) });
  }

  return (
    <div className="appearance-controls" aria-label="裁切框外觀設定">
      <label>
        <span>線寬 <strong>{boxStyle.strokeWidth}px</strong></span>
        <input
          aria-label="線條粗細"
          type="range"
          min="1"
          max="8"
          step="1"
          value={boxStyle.strokeWidth}
          onInput={updateStrokeWidth}
          onChange={updateStrokeWidth}
        />
      </label>
      <label>
        <span>透明度 <strong>{boxStyle.opacity}%</strong></span>
        <input
          aria-label="透明度"
          type="range"
          min="20"
          max="100"
          step="5"
          value={boxStyle.opacity}
          onInput={updateOpacity}
          onChange={updateOpacity}
        />
      </label>
      <div className="color-control">
        <div className="color-swatches">
          {BOX_COLORS.map((color) => (
            <button
              key={color.value}
              type="button"
              className={boxStyle.color === color.value ? "selected" : ""}
              style={{ "--swatch-color": color.value }}
              aria-label={color.name}
              title={color.name}
              onClick={() => onChange({ ...boxStyle, color: color.value })}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function CropOverlay({
  activeTool,
  boxes,
  boxStyle,
  draft,
  imageSize,
  selectedId,
  onBoxPointerDown,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  overlayRef,
}) {
  return (
    <svg
      ref={overlayRef}
      className={`crop-overlay ${activeTool}-mode`}
      style={{
        "--box-color": boxStyle.color,
        "--box-stroke-width": boxStyle.strokeWidth,
        "--box-opacity": boxStyle.opacity / 100,
        "--box-fill-opacity": (boxStyle.opacity / 100) * 0.28,
      }}
      viewBox={`0 0 ${imageSize.width} ${imageSize.height}`}
      aria-label="裁切框標註區"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      {boxes.map((box) => {
        const isSelected = box.id === selectedId;
        const labelY = Math.max(0, box.y - 36);
        return (
          <g
            key={box.id}
            className={`box-group ${isSelected ? "selected" : ""}`}
            data-box-id={box.id}
            onPointerDown={(event) => onBoxPointerDown(event, box.id)}
          >
            <rect className="box-rect" x={box.x} y={box.y} width={box.width} height={box.height} />
            <rect className="box-label" x={box.x} y={labelY} width="46" height="36" />
            <text className="box-label-text" x={box.x + 23} y={labelY + 18}>{box.id}</text>
            {isSelected && RESIZE_HANDLES.map((handle) => (
              <rect
                key={handle.name}
                className={`resize-handle resize-${handle.name}`}
                x={handle.x(box) - 10}
                y={handle.y(box) - 10}
                width="20"
                height="20"
                data-handle={handle.name}
                onPointerDown={(event) => onBoxPointerDown(event, box.id, handle.name)}
              />
            ))}
          </g>
        );
      })}
      {draft && (
        <rect
          className="draft-rect"
          x={draft.x}
          y={draft.y}
          width={draft.width}
          height={draft.height}
        />
      )}
    </svg>
  );
}

function RecognitionOverlay({
  imageSize,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  overlayRef,
  results,
  visible,
}) {
  return (
    <svg
      ref={overlayRef}
      className="recognition-overlay"
      viewBox={`0 0 ${imageSize.width} ${imageSize.height}`}
      aria-label="OCR 辨識結果標註層"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      {visible && results.map((result) => {
        const box = result.box;
        const onRight = box.x + box.width / 2 >= imageSize.width / 2;
        const boxEdge = onRight ? box.x + box.width : box.x;
        const labelX = boxEdge + (onRight ? 24 : -24);
        const labelY = box.y + box.height / 2;
        return (
          <g key={result.crop_number} className="recognition-result">
            <rect
              className="recognition-box"
              x={box.x}
              y={box.y}
              width={box.width}
              height={box.height}
            />
            <line
              className="recognition-leader"
              x1={boxEdge}
              y1={labelY}
              x2={labelX}
              y2={labelY}
            />
            <text
              className="recognition-text"
              x={labelX + (onRight ? 8 : -8)}
              y={labelY}
              textAnchor={onRight ? "start" : "end"}
            >
              {result.ocr}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function App() {
  const [documents, setDocuments] = useState([]);
  const [documentName, setDocumentName] = useState("");
  const [page, setPage] = useState(1);
  const [boxes, setBoxes] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [activeTool, setActiveTool] = useState("select");
  const [draft, setDraft] = useState(null);
  const [interaction, setInteraction] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [boxStyle, setBoxStyle] = useState({ strokeWidth: 1, opacity: 45, color: BOX_COLORS[3].value });
  const [imageSize, setImageSize] = useState(EMPTY_IMAGE_SIZE);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [jobResult, setJobResult] = useState(null);
  const [ocrResult, setOcrResult] = useState(null);
  const [recognizing, setRecognizing] = useState(false);
  const [viewMode, setViewMode] = useState("edit");
  const [layers, setLayers] = useState({ drawing: true, recognition: true });
  const [toast, setToast] = useState("");

  const overlayRef = useRef(null);
  const viewportRef = useRef(null);
  const drawingSurfaceRef = useRef(null);
  const toastTimerRef = useRef(null);
  const loadIdRef = useRef("");

  const currentDocument = useMemo(
    () => documents.find((document) => document.name === documentName),
    [documents, documentName],
  );
  const selectedBox = boxes.find((box) => box.id === selectedId);
  const previewUrl = documentName
    ? `/api/documents/${encodeURIComponent(documentName)}/pages/${page}/preview?scale=${PREVIEW_RENDER_SCALE}`
    : "";

  function showToast(message) {
    setToast(message);
    window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(""), 2600);
  }

  function resetBoxes() {
    setBoxes([]);
    setSelectedId(null);
    setDraft(null);
    setInteraction(null);
  }

  function clampPan(nextPan, nextZoom = zoom) {
    if (!viewportRef.current || !drawingSurfaceRef.current) return nextPan;
    const viewportWidth = viewportRef.current.clientWidth - 60;
    const viewportHeight = viewportRef.current.clientHeight - 60;
    const maxX = Math.max(0, (drawingSurfaceRef.current.offsetWidth * nextZoom - viewportWidth) / 2);
    const maxY = Math.max(0, (drawingSurfaceRef.current.offsetHeight * nextZoom - viewportHeight) / 2);
    return {
      x: clamp(nextPan.x, -maxX, maxX),
      y: clamp(nextPan.y, -maxY, maxY),
    };
  }

  function resetView() {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }

  function selectTool(tool) {
    setActiveTool(tool);
    setDraft(null);
    setInteraction(null);
  }

  function confirmDiscard() {
    return boxes.length === 0 || window.confirm("切換圖面會清除目前框選，確定繼續嗎？");
  }

  function beginPageLoad() {
    loadIdRef.current = createLoadId();
    setLoading(true);
    setLoadError("");
    setImageSize(EMPTY_IMAGE_SIZE);
    setJobResult(null);
    setOcrResult(null);
    setViewMode("edit");
    setLayers({ drawing: true, recognition: true });
    resetBoxes();
    resetView();
  }

  useEffect(() => {
    let active = true;
    async function loadDocuments() {
      try {
        const response = await fetch("/api/documents");
        if (!response.ok) throw new Error("無法取得 PDF 清單");
        const result = await response.json();
        if (!result.length) throw new Error("test-ED 中沒有 PDF");
        if (!active) return;
        setDocuments(result);
        setDocumentName(result[0].name);
      } catch (error) {
        if (!active) return;
        setLoading(false);
        setLoadError(error.message);
        showToast(error.message);
      }
    }
    loadDocuments();
    return () => {
      active = false;
      window.clearTimeout(toastTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (documentName) beginPageLoad();
  }, [documentName, page]);

  useEffect(() => {
    function handleKeyDown(event) {
      if (["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName)) return;
      if (viewMode !== "edit") return;
      if (event.key === "Delete") deleteSelected();
      if (event.key.toLowerCase() === "v") selectTool("select");
      if (event.key.toLowerCase() === "c") selectTool("crop");
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  function pointFromEvent(event) {
    const bounds = overlayRef.current.getBoundingClientRect();
    return {
      x: clamp((event.clientX - bounds.left) * imageSize.width / bounds.width, 0, imageSize.width),
      y: clamp((event.clientY - bounds.top) * imageSize.height / bounds.height, 0, imageSize.height),
    };
  }

  function capturePointer(pointerId) {
    if (overlayRef.current && !overlayRef.current.hasPointerCapture(pointerId)) {
      overlayRef.current.setPointerCapture(pointerId);
    }
  }

  function handleOverlayPointerDown(event) {
    if (!imageSize.width) return;
    capturePointer(event.pointerId);

    if (viewMode === "recognition" || activeTool === "select") {
      setSelectedId(null);
      setInteraction({
        type: "pan",
        start: { x: event.clientX, y: event.clientY },
        original: { ...pan },
      });
      return;
    }

    const start = pointFromEvent(event);
    setSelectedId(null);
    setDraft({ ...start, width: 0, height: 0, start });
  }

  function handleBoxPointerDown(event, boxId, handle = null) {
    if (viewMode !== "edit") return;
    event.stopPropagation();
    capturePointer(event.pointerId);
    const box = boxes.find((current) => current.id === boxId);
    if (!box) return;

    setSelectedId(boxId);
    setInteraction({
      type: handle ? "resize" : "move",
      handle,
      boxId,
      start: pointFromEvent(event),
      original: { ...box },
    });
  }

  function handlePointerMove(event) {
    if (interaction?.type === "pan") {
      setPan(clampPan({
        x: interaction.original.x + event.clientX - interaction.start.x,
        y: interaction.original.y + event.clientY - interaction.start.y,
      }));
      return;
    }

    const point = pointFromEvent(event);

    if (draft) {
      setDraft({ ...normalizedBox(draft.start, point), start: draft.start });
      return;
    }

    if (!interaction) return;
    let nextBox;
    if (interaction.type === "move") {
      const deltaX = point.x - interaction.start.x;
      const deltaY = point.y - interaction.start.y;
      nextBox = {
        ...interaction.original,
        x: clamp(interaction.original.x + deltaX, 0, imageSize.width - interaction.original.width),
        y: clamp(interaction.original.y + deltaY, 0, imageSize.height - interaction.original.height),
      };
    } else {
      nextBox = {
        ...interaction.original,
        ...resizedBox(interaction.original, interaction.handle, point, imageSize),
      };
    }

    setBoxes((current) => current.map((box) => box.id === interaction.boxId ? nextBox : box));
  }

  function handlePointerUp(event) {
    if (draft) {
      const box = normalizedBox(draft.start, pointFromEvent(event));
      setDraft(null);
      if (box.width >= MIN_BOX_SIZE && box.height >= MIN_BOX_SIZE) {
        const id = boxes.length + 1;
        setBoxes((current) => [...current, { id, ...box }]);
        setSelectedId(id);
      }
    }
    setInteraction(null);
  }

  function handleWheel(event) {
    if (!imageSize.width) return;
    event.preventDefault();
    const nextZoom = clamp(zoom * (event.deltaY < 0 ? 1.12 : 0.89), MIN_ZOOM, MAX_ZOOM);
    if (nextZoom === zoom) return;

    const bounds = viewportRef.current.getBoundingClientRect();
    const pointer = {
      x: event.clientX - bounds.left - bounds.width / 2,
      y: event.clientY - bounds.top - bounds.height / 2,
    };
    const scaleRatio = nextZoom / zoom;
    const nextPan = {
      x: pointer.x - (pointer.x - pan.x) * scaleRatio,
      y: pointer.y - (pointer.y - pan.y) * scaleRatio,
    };

    setZoom(nextZoom);
    setPan(clampPan(nextPan, nextZoom));
  }

  function deleteSelected() {
    if (viewMode !== "edit" || selectedId === null) return;
    setBoxes((current) =>
      current
        .filter((box) => box.id !== selectedId)
        .map((box, index) => ({ ...box, id: index + 1 })),
    );
    setSelectedId(null);
    setInteraction(null);
    showToast("已刪除選取框，編號已依原順序重新排列");
  }

  function changeDocument(nextDocument) {
    if (!confirmDiscard()) return;
    setDocumentName(nextDocument);
    setPage(1);
  }

  function changePage(nextPage) {
    if (!confirmDiscard()) return;
    setPage(nextPage);
  }

  async function submitJob(action) {
    setBusy(true);
    setJobResult(null);
    try {
      const response = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document: documentName, page, load_id: loadIdRef.current, boxes, action }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "輸出失敗");
      setJobResult({ ...result, action, revision: Date.now() });
      showToast(action === "crop" ? "裁切結果已輸出" : "標註資料已儲存");
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitRecognition() {
    setBusy(true);
    setRecognizing(true);
    setJobResult(null);
    try {
      const cropResponse = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document: documentName,
          page,
          load_id: loadIdRef.current,
          boxes,
          action: "crop",
        }),
      });
      const cropResult = await cropResponse.json();
      if (!cropResponse.ok) throw new Error(cropResult.detail || "裁切資料更新失敗");

      const response = await fetch(`/api/jobs/${encodeURIComponent(cropResult.job_id)}/ocr`, {
        method: "POST",
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "辨識失敗");

      setOcrResult(result);
      setJobResult({ ...cropResult, action: "ocr", revision: Date.now() });
      setSelectedId(null);
      setInteraction(null);
      setViewMode("recognition");
      setLayers({ drawing: true, recognition: true });
      showToast("OCR 辨識完成");
    } catch (error) {
      showToast(error.message);
    } finally {
      setRecognizing(false);
      setBusy(false);
    }
  }

  function returnToEdit() {
    setViewMode("edit");
    setSelectedId(null);
    setInteraction(null);
    setActiveTool("select");
    showToast("已返回標註編輯模式");
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">ED</span>
          <div>
            <p>ENGINEERING DRAWING</p>
            <h1>圖面工作台</h1>
          </div>
        </div>
        <div className="system-pill"><span /> 本機處理服務已就緒</div>
      </header>

      <aside className="side-panel source-panel">
        <section>
          <SectionHeading step="01" eyebrow="SOURCE" title="圖面來源" />
          <label className="field-label" htmlFor="document-select">PDF 文件</label>
          <select
            id="document-select"
            value={documentName}
            disabled={busy || !documents.length}
            onChange={(event) => changeDocument(event.target.value)}
          >
            {!documents.length && <option>正在讀取 test-ED...</option>}
            {documents.map((document) => <option key={document.name}>{document.name}</option>)}
          </select>

          <div className="page-nav">
            <button
              className="square-button"
              aria-label="上一頁"
              disabled={busy || page <= 1}
              onClick={() => changePage(page - 1)}
            >←</button>
            <div>
              <span>頁面</span>
              <strong>{currentDocument ? `${page} / ${currentDocument.pages}` : "-- / --"}</strong>
            </div>
            <button
              className="square-button"
              aria-label="下一頁"
              disabled={busy || !currentDocument || page >= currentDocument.pages}
              onClick={() => changePage(page + 1)}
            >→</button>
          </div>
        </section>

        <section>
          <SectionHeading step="02" eyebrow="TOOLS" title="標註工具" />
          {viewMode === "recognition" ? (
            <ToolButton
              active
              icon={<SelectIcon />}
              title="重新編輯"
              description="保留目前 box，返回標註模式"
              shortcut="EDIT"
              onClick={returnToEdit}
            />
          ) : (
            <>
              <ToolButton
                active={activeTool === "select"}
                icon={<SelectIcon />}
                title="選取／調整"
                description="選取、移動或調整 box 大小"
                shortcut="V"
                onClick={() => selectTool("select")}
              />
              <ToolButton
                active={activeTool === "crop"}
                icon={<CropIcon />}
                title="框選裁切區域"
                description="空白處建立，框可直接調整"
                shortcut="C"
                onClick={() => selectTool("crop")}
              />
              <button className="tool-button danger" disabled={busy || selectedId === null} onClick={deleteSelected}>
                <span className="delete-icon" aria-hidden="true">×</span>
                <div><strong>刪除選取框</strong><small>其餘編號會自動補位</small></div>
                <kbd>DEL</kbd>
              </button>
              <button
                className="ghost-button full-width"
                disabled={busy || boxes.length === 0}
                onClick={() => {
                  if (window.confirm("確定清除全部框選嗎？")) {
                    resetBoxes();
                    showToast("已清除全部框選");
                  }
                }}
              >清除全部框選</button>
            </>
          )}
        </section>

        <section className="tip-card">
          <strong>操作提示</strong>
          <p>滾動滑鼠縮放圖面；建立 box 後可直接拖曳或調整四角。選取模式下拖曳空白處可平移圖面。</p>
        </section>
      </aside>

      <main className="workspace">
        <div className="workspace-bar">
          <div className="document-meta">
            <strong>{documentName || "NO DOCUMENT"}</strong>
            <span>{imageSize.width ? `${imageSize.width} × ${imageSize.height} PX` : "-- × -- PX"}</span>
          </div>
          {viewMode === "edit" ? (
            <AppearanceControls boxStyle={boxStyle} onChange={setBoxStyle} />
          ) : (
            <div className="recognition-mode-label">
              <span>OCR VIEW</span>
              <strong>辨識結果檢視</strong>
            </div>
          )}
          <p className="box-count"><strong>{boxes.length}</strong> 個裁切框</p>
        </div>

        <div
          ref={viewportRef}
          className={`canvas-viewport ${interaction?.type === "pan" ? "is-panning" : ""}`}
          onWheel={handleWheel}
        >
          {(loading || recognizing) && (
            <div className="loading-state" role="status">
              <span />
              <strong>{recognizing ? "執行圖面辨識中" : "載入工程圖面中"}</strong>
              <small>{recognizing ? "正在分析 crop 圖片與符號" : "正在建立高解析度預覽"}</small>
            </div>
          )}
          {viewMode === "recognition" && (
            <div className="layer-panel" aria-label="圖面顯示圖層">
              <span className="layer-panel-title">LAYERS</span>
              <button
                className={layers.recognition ? "active" : ""}
                type="button"
                onClick={() => setLayers((current) => ({ ...current, recognition: !current.recognition }))}
              >
                <i className="layer-swatch recognition-swatch" />
                <span><strong>OCR 標註</strong><small>螢光辨識結果</small></span>
                <b>{layers.recognition ? "ON" : "OFF"}</b>
              </button>
              <button
                className={layers.drawing ? "active" : ""}
                type="button"
                onClick={() => setLayers((current) => ({ ...current, drawing: !current.drawing }))}
              >
                <i className="layer-swatch drawing-swatch" />
                <span><strong>圖面底圖</strong><small>原始工程圖面</small></span>
                <b>{layers.drawing ? "ON" : "OFF"}</b>
              </button>
            </div>
          )}
          {loadError && !loading && <div className="error-state">{loadError}</div>}
          {previewUrl && (
            <div
              ref={drawingSurfaceRef}
              className={`drawing-surface ${loading || recognizing ? "is-loading" : ""} ${viewMode === "recognition" ? "recognition-mode" : ""}`}
              style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}
            >
              <img
                className={viewMode === "recognition" && !layers.drawing ? "layer-hidden" : ""}
                key={previewUrl}
                src={previewUrl}
                alt="PDF page snapshot"
                draggable="false"
                onLoad={(event) => {
                  const coordinateRatio = CROP_COORDINATE_SCALE / PREVIEW_RENDER_SCALE;
                  setImageSize({
                    width: event.currentTarget.naturalWidth * coordinateRatio,
                    height: event.currentTarget.naturalHeight * coordinateRatio,
                  });
                  setLoading(false);
                }}
                onError={() => {
                  setLoading(false);
                  setLoadError("PDF 頁面預覽載入失敗");
                }}
              />
              {imageSize.width > 0 && viewMode === "edit" && (
                <CropOverlay
                  activeTool={activeTool}
                  boxes={boxes}
                  boxStyle={boxStyle}
                  draft={draft}
                  imageSize={imageSize}
                  selectedId={selectedId}
                  onBoxPointerDown={handleBoxPointerDown}
                  onPointerDown={handleOverlayPointerDown}
                  onPointerMove={handlePointerMove}
                  onPointerUp={handlePointerUp}
                  overlayRef={overlayRef}
                />
              )}
              {imageSize.width > 0 && viewMode === "recognition" && ocrResult && (
                <RecognitionOverlay
                  imageSize={imageSize}
                  onPointerDown={handleOverlayPointerDown}
                  onPointerMove={handlePointerMove}
                  onPointerUp={handlePointerUp}
                  overlayRef={overlayRef}
                  results={ocrResult.results}
                  visible={layers.recognition}
                />
              )}
            </div>
          )}
        </div>
      </main>

      <aside className="side-panel action-panel">
        <section>
          <SectionHeading step="03" eyebrow="SELECTION" title="目前選取" />
          {viewMode === "recognition" ? (
            <div className="recognition-summary">
              <strong>{ocrResult?.results.length || 0}</strong>
              <span>筆 OCR 辨識結果</span>
              <small>可使用工作區右上角圖層按鈕進行對比</small>
            </div>
          ) : !selectedBox ? (
            <div className="empty-card">尚未選取任何裁切框</div>
          ) : (
            <dl className="selection-details">
              <div><dt>BOX ID</dt><dd>#{String(selectedBox.id).padStart(2, "0")}</dd></div>
              <div><dt>座標</dt><dd>X {Math.round(selectedBox.x)} / Y {Math.round(selectedBox.y)}</dd></div>
              <div><dt>尺寸</dt><dd>{Math.round(selectedBox.width)} × {Math.round(selectedBox.height)} PX</dd></div>
            </dl>
          )}
        </section>

        <section className="output-section">
          <SectionHeading step="04" eyebrow="OUTPUT" title="輸出作業" />
          <button
            className="ghost-button full-width action-button"
            disabled={busy || boxes.length === 0 || viewMode === "recognition"}
            onClick={() => submitJob("crop")}
          >儲存標註資料</button>
          <button
            className="primary-button"
            type="button"
            disabled={busy || boxes.length === 0 || viewMode === "recognition"}
            onClick={submitRecognition}
          >
            <span>{recognizing ? "辨識處理中" : "執行辨識"}</span>
            <span aria-hidden="true">→</span>
          </button>
          {jobResult && (
            <div className="job-result" key={jobResult.revision}>
              <span className="result-status">
                {jobResult.action === "ocr" ? "辨識完成" : jobResult.action === "crop" ? "裁切完成" : "標註已儲存"}
              </span>
              <strong className="result-path">{jobResult.output_dir}</strong>
              <div className="crop-preview-list">
                {jobResult.files
                  .filter((file) => /\/crop_\d+\.png$/.test(file))
                  .map((file) => {
                    const boxNumber = file.match(/crop_(\d+)\.png$/)?.[1];
                    return (
                      <figure className="crop-preview" key={file}>
                        <figcaption><span>BOX</span><b>#{boxNumber}</b></figcaption>
                        <img
                          src={`${file}?revision=${jobResult.revision}`}
                          alt={`Box ${boxNumber} 裁切圖片`}
                          loading="lazy"
                        />
                      </figure>
                    );
                  })}
              </div>
            </div>
          )}
        </section>
      </aside>

      <div className={`toast ${toast ? "show" : ""}`} role="status" aria-live="polite">{toast}</div>
    </div>
  );
}

export default App;
