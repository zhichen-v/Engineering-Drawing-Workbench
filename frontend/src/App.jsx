import { useEffect, useRef, useState } from "react";

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

function getFramePage(frameDetection, page) {
  return frameDetection?.pages?.find((framePage) => framePage.page === page) || null;
}

function framePageIsReady(framePage) {
  return Boolean(framePage?.columns?.length && framePage?.rows?.length);
}

function locateFrameCell(framePage, box) {
  if (!framePageIsReady(framePage) || !box) return null;
  const centerX = box.x + box.width / 2;
  const centerY = box.y + box.height / 2;
  const column = framePage.columns.find((cell) => centerX >= cell.min && centerX <= cell.max);
  const row = framePage.rows.find((cell) => centerY >= cell.min && centerY <= cell.max);
  return row && column ? `${row.label}${column.label}` : null;
}

function boxCenter(box) {
  if (!box) return null;
  return {
    x: box.x + box.width / 2,
    y: box.y + box.height / 2,
  };
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
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

function FrameIcon() {
  return <span className="frame-icon" aria-hidden="true" />;
}

function LoadingArc() {
  return (
    <svg className="initialized-loader" viewBox="0 0 200 200" aria-hidden="true">
      <circle className="initialized-loader__arc" cx="100" cy="100" r="78" pathLength="100" />
    </svg>
  );
}

function ToolButton({
  active,
  attention = false,
  disabled = false,
  icon,
  title,
  description,
  shortcut,
  onClick,
}) {
  return (
    <button
      className={`tool-button ${active ? "active" : ""} ${attention ? "attention" : ""}`}
      disabled={disabled}
      onClick={onClick}
    >
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
  onPointerLost,
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
      onPointerCancel={onPointerLost}
      onLostPointerCapture={onPointerLost}
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
                x={handle.x(box) - 4}
                y={handle.y(box) - 4}
                width="8"
                height="8"
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

function FrameDetectionOverlay({ revision, src, visible }) {
  if (!src || !visible) return null;
  return (
    <img
      className="frame-detection-overlay"
      src={`${src}?revision=${revision}`}
      alt=""
      aria-hidden="true"
      draggable="false"
    />
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
        const numberY = Math.max(0, box.y - 36);
        return (
          <g
            key={result.crop_number}
            className={`recognition-result ${result.abnormal ? "abnormal" : ""}`}
          >
            <rect
              className="recognition-box"
              x={box.x}
              y={box.y}
              width={box.width}
              height={box.height}
            />
            <rect className="recognition-number-box" x={box.x} y={numberY} width="46" height="36" />
            <text className="box-label-text" x={box.x + 23} y={numberY + 18}>
              {result.crop_number}
            </text>
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
  const [currentDocument, setCurrentDocument] = useState(null);
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
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [jobResult, setJobResult] = useState(null);
  const [savedJobId, setSavedJobId] = useState("");
  const [savedBoxesSignature, setSavedBoxesSignature] = useState("");
  const [ocrResult, setOcrResult] = useState(null);
  const [recognizing, setRecognizing] = useState(false);
  const [recognitionComplete, setRecognitionComplete] = useState(false);
  const [ocrStage, setOcrStage] = useState("model_loading");
  const [ocrProgress, setOcrProgress] = useState({ current: 0, total: 0, reused: 0, crop: "" });
  const [frameDetection, setFrameDetection] = useState(null);
  const [detectingFrame, setDetectingFrame] = useState(false);
  const [frameLayerVisible, setFrameLayerVisible] = useState(true);
  const [viewMode, setViewMode] = useState("edit");
  const [recognitionVisible, setRecognitionVisible] = useState(true);
  const [excelFormat, setExcelFormat] = useState("MIP");
  const [excelResults, setExcelResults] = useState({});
  const [excelPreviewIndex, setExcelPreviewIndex] = useState(0);
  const [excelGenerating, setExcelGenerating] = useState(false);
  const [toast, setToast] = useState("");

  const overlayRef = useRef(null);
  const viewportRef = useRef(null);
  const drawingSurfaceRef = useRef(null);
  const toastTimerRef = useRef(null);
  const loadIdRef = useRef("");
  const pageBoxesRef = useRef({});

  const documentName = currentDocument?.id || "";
  const selectedBox = boxes.find((box) => box.id === selectedId);
  const previewUrl = documentName
    ? `/api/documents/${encodeURIComponent(documentName)}/pages/${page}/preview?scale=${PREVIEW_RENDER_SCALE}`
    : "";
  const documentBoxes = Object.entries(pageBoxesRef.current)
    .filter(([pageNumber]) => Number(pageNumber) !== page)
    .flatMap(([pageNumber, pageBoxes]) => pageBoxes.map((box) => ({ ...box, page: Number(pageNumber) })))
    .concat(boxes.map((box) => ({ ...box, page })))
    .sort((left, right) => left.id - right.id);
  const boxesSignature = JSON.stringify(documentBoxes);
  const hasUnsavedBoxes = documentBoxes.length > 0 && boxesSignature !== savedBoxesSignature;
  const currentOcrResults = (ocrResult?.results || []).filter(
    (result) => (result.box.page || 1) === page,
  );
  const currentFramePage = getFramePage(frameDetection, page);
  const frameGridReady = framePageIsReady(currentFramePage);
  const frameOverlayUrl = frameDetection?.overlays?.[String(page)] || "";
  const selectedFrameLocation = locateFrameCell(currentFramePage, selectedBox);
  const excelResult = excelResults[excelFormat] || null;
  const currentExcelPreview = excelResult?.previews?.[excelPreviewIndex] || null;
  const ocrProgressText = ocrProgress.total
    ? `${Math.min(ocrProgress.current, ocrProgress.total)} / ${ocrProgress.total}`
    : "";
  const recognitionButtonText = recognizing
    ? "辨識處理中"
    : recognitionComplete
      ? "完成辨識"
      : "執行辨識";
  const canvasBusyTitle = detectingFrame
    ? "執行圖框識別中"
    : recognizing
      ? (ocrStage === "model_loading" ? "載入 OCR 模型中" : "OCR 辨識中")
      : excelGenerating
        ? `產生 ${excelFormat} Excel 中`
        : viewMode === "excel"
          ? "載入 Excel 預覽中"
          : "載入工程圖面中";
  const canvasBusyDetail = detectingFrame
    ? "正在建立圖框座標與 overlay"
    : recognizing
      ? (
        ocrStage === "model_loading"
          ? "正在準備 GLM-OCR 與符號模型，首次啟動會較久"
          : `模型已就緒，正在辨識 crop ${ocrProgressText || ""}`.trim()
      )
      : excelGenerating
        ? "正在填入表單並建立 Excel 預覽截圖"
        : viewMode === "excel"
          ? "正在載入工作表預覽"
          : "正在建立高解析度預覽";

  function showToast(message) {
    setToast(message);
    window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(""), 2600);
  }

  function resetBoxes() {
    pageBoxesRef.current = {};
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
    if (!frameGridReady) {
      showToast("請先執行圖框識別");
      return;
    }
    setActiveTool(tool);
    setDraft(null);
    setInteraction(null);
  }

  function confirmDiscard() {
    return documentBoxes.length === 0 || window.confirm("切換文件會清除目前框選，確定繼續嗎？");
  }

  function beginDocumentLoad() {
    loadIdRef.current = createLoadId();
    setJobResult(null);
    setSavedJobId("");
    setSavedBoxesSignature("");
    setOcrResult(null);
    setRecognitionComplete(false);
    setOcrStage("model_loading");
    setOcrProgress({ current: 0, total: 0, reused: 0, crop: "" });
    setFrameDetection(null);
    setDetectingFrame(false);
    setFrameLayerVisible(true);
    setViewMode("edit");
    setRecognitionVisible(true);
    setExcelResults({});
    setExcelPreviewIndex(0);
    setExcelGenerating(false);
    resetBoxes();
  }

  function beginPageLoad() {
    setLoading(true);
    setLoadError("");
    setImageSize(EMPTY_IMAGE_SIZE);
    setSelectedId(null);
    setDraft(null);
    setInteraction(null);
    resetView();
  }

  useEffect(() => {
    return () => window.clearTimeout(toastTimerRef.current);
  }, []);

  useEffect(() => {
    if (documentName) beginDocumentLoad();
  }, [documentName]);

  useEffect(() => {
    if (documentName) beginPageLoad();
  }, [documentName, page]);

  useEffect(() => {
    function handleKeyDown(event) {
      if (["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName)) return;
      if (viewMode !== "edit") return;
      if (!frameGridReady) return;
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

    if (viewMode !== "edit" || activeTool === "select") {
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
        const id = Math.max(0, ...documentBoxes.map((box) => box.id)) + 1;
        setBoxes((current) => [...current, { id, ...box }]);
        setSelectedId(id);
      }
    }
    setInteraction(null);
  }

  function handlePointerLost() {
    setDraft(null);
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
    const grouped = {};
    documentBoxes
      .filter((box) => box.id !== selectedId)
      .map((box, index) => ({ ...box, id: index + 1 }))
      .forEach(({ page: boxPage, ...box }) => {
        grouped[boxPage] = [...(grouped[boxPage] || []), box];
      });
    pageBoxesRef.current = grouped;
    setBoxes(grouped[page] || []);
    setSelectedId(null);
    setInteraction(null);
    showToast("已刪除選取框");
  }

  async function uploadDocument(file) {
    if (!file?.name.toLowerCase().endsWith(".pdf")) {
      showToast("未選擇任何 PDF");
      return;
    }
    if (!confirmDiscard()) return;

    setUploading(true);
    try {
      const response = await fetch(`/api/documents/upload?filename=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers: { "Content-Type": "application/pdf" },
        body: file,
      });
      const uploaded = await response.json();
      if (!response.ok) throw new Error(uploaded.detail || `無法上傳 ${file.name}`);
      setCurrentDocument(uploaded);
      setPage(1);
      showToast("PDF 已載入");
    } catch (error) {
      showToast(error.message);
    } finally {
      setUploading(false);
    }
  }

  function changePage(nextPage) {
    pageBoxesRef.current[page] = boxes;
    setBoxes(pageBoxesRef.current[nextPage] || []);
    setSelectedId(null);
    setDraft(null);
    setInteraction(null);
    setPage(nextPage);
  }

  async function submitFrameDetection() {
    setBusy(true);
    setDetectingFrame(true);
    try {
      const response = await fetch("/api/frame-detection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document: documentName,
          page,
          load_id: loadIdRef.current,
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "圖框識別失敗");

      const nextFrameDetection = { ...result, revision: Date.now() };
      const readyPages = (result.pages || []).filter(framePageIsReady).length;
      const currentPageReady = framePageIsReady(getFramePage(nextFrameDetection, page));
      setFrameDetection(nextFrameDetection);
      setFrameLayerVisible(true);
      setActiveTool("select");
      showToast(currentPageReady ? `圖框識別完成，${readyPages} 頁可定位` : "目前頁面尚未取得格位座標");
    } catch (error) {
      showToast(error.message);
    } finally {
      setDetectingFrame(false);
      setBusy(false);
    }
  }

  async function submitJob(action) {
    if (!frameGridReady) {
      showToast("請先執行圖框識別");
      return;
    }
    setBusy(true);
    setJobResult(null);
    try {
      const response = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document: documentName,
          page,
          load_id: loadIdRef.current,
          boxes: documentBoxes,
          action,
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "輸出失敗");
      setJobResult({ ...result, action, revision: Date.now() });
      if (action === "crop") {
        setSavedJobId(result.job_id);
        setSavedBoxesSignature(boxesSignature);
      }
      showToast(action === "crop" ? "裁切結果已輸出" : "標註資料已儲存");
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(false);
    }
  }

  function applyOcrTaskStatus(task) {
    setOcrStage(task.stage || "model_loading");
    setOcrProgress({
      current: Number(task.current || 0),
      total: Number(task.total || 0),
      reused: Number(task.reused || 0),
      crop: task.crop || "",
    });
  }

  async function waitForOcrTask(jobId, taskId) {
    while (true) {
      await delay(650);
      const response = await fetch(
        `/api/jobs/${encodeURIComponent(jobId)}/ocr/tasks/${encodeURIComponent(taskId)}`,
      );
      const task = await response.json();
      if (!response.ok) throw new Error(task.detail || "無法取得 OCR 進度");
      applyOcrTaskStatus(task);
      if (task.status === "completed") return task.result;
      if (task.status === "failed") throw new Error(task.error || task.message || "辨識失敗");
    }
  }

  async function submitRecognition() {
    if (!frameGridReady) {
      showToast("請先執行圖框識別");
      return;
    }
    if (hasUnsavedBoxes || !savedJobId) {
      showToast("裁切框有變動，請先儲存標註資料");
      return;
    }
    setBusy(true);
    setRecognizing(true);
    setRecognitionComplete(false);
    setExcelResults({});
    setOcrStage("model_loading");
    setOcrProgress({ current: 0, total: documentBoxes.length, reused: 0, crop: "" });
    setJobResult(null);
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(savedJobId)}/ocr/tasks`, {
        method: "POST",
      });
      const task = await response.json();
      if (!response.ok) throw new Error(task.detail || "辨識任務啟動失敗");
      applyOcrTaskStatus(task);

      const result = await waitForOcrTask(savedJobId, task.task_id);

      setOcrResult(result);
      setRecognitionComplete(true);
      setSelectedId(null);
      setInteraction(null);
      setViewMode("recognition");
      setRecognitionVisible(true);
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
    setRecognitionComplete(false);
    setSelectedId(null);
    setInteraction(null);
    setActiveTool("select");
    showToast("已返回標註編輯模式");
  }

  function returnToRecognition() {
    setViewMode("recognition");
    setSelectedId(null);
    setInteraction(null);
    setLoading(true);
    resetView();
    showToast("已返回 OCR 辨識結果");
  }

  function changeExcelFormat(format) {
    setExcelFormat(format);
    setExcelPreviewIndex(0);
    if (excelResults[format]) {
      setViewMode("excel");
      setLoading(true);
      resetView();
      showToast(`${format} Excel 預覽已載入`);
    } else if (viewMode === "excel") {
      returnToRecognition();
    }
  }

  async function submitExcel() {
    if (!recognitionComplete || !ocrResult || !savedJobId) {
      showToast("請先完成 OCR 辨識");
      return;
    }

    if (excelResult) {
      setExcelPreviewIndex(0);
      setViewMode("excel");
      setLoading(true);
      resetView();
      showToast(`${excelFormat} Excel 預覽已載入`);
      return;
    }

    setBusy(true);
    setExcelGenerating(true);
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(savedJobId)}/excel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ format: excelFormat }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Excel 輸出失敗");

      setExcelResults((current) => ({
        ...current,
        [excelFormat]: { ...result, revision: Date.now() },
      }));
      setExcelPreviewIndex(0);
      setViewMode("excel");
      setLoading(true);
      resetView();
      showToast(`${excelFormat} Excel 已產生`);
    } catch (error) {
      showToast(error.message);
    } finally {
      setExcelGenerating(false);
      setBusy(false);
    }
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
          <label className="source-file-button">
            <input
              type="file"
              accept=".pdf,application/pdf"
              disabled={busy || uploading}
              onChange={(event) => {
                uploadDocument(event.target.files[0]);
                event.target.value = "";
              }}
            />
            {uploading ? "上傳中…" : "選擇 PDF"}
          </label>

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
          {viewMode !== "edit" ? (
            <ToolButton
              active
              icon={<SelectIcon />}
              title={viewMode === "excel" ? "返回 OCR 結果" : "重新編輯"}
              description={viewMode === "excel" ? "關閉 Excel 預覽" : "保留目前 box，返回標註模式"}
              shortcut={viewMode === "excel" ? "OCR" : "EDIT"}
              onClick={viewMode === "excel" ? returnToRecognition : returnToEdit}
            />
          ) : (
            <>
              <ToolButton
                active={frameGridReady}
                attention={!frameGridReady && !detectingFrame}
                disabled={busy || loading || !documentName}
                icon={<FrameIcon />}
                title={detectingFrame ? "圖框識別中" : "圖框識別"}
                description={frameGridReady ? `${currentFramePage.columns.length} 欄 / ${currentFramePage.rows.length} 列已定位` : "標註前先建立格位座標"}
                shortcut={frameGridReady ? "OK" : "REQ"}
                onClick={submitFrameDetection}
              />
              <ToolButton
                active={frameGridReady && activeTool === "select"}
                disabled={busy || !frameGridReady}
                icon={<SelectIcon />}
                title="選取／調整"
                description="移動、調整 box 大小"
                shortcut="V"
                onClick={() => selectTool("select")}
              />
              <ToolButton
                active={frameGridReady && activeTool === "crop"}
                disabled={busy || !frameGridReady}
                icon={<CropIcon />}
                title="框選裁切區域"
                description="可直接調整大小"
                shortcut="C"
                onClick={() => selectTool("crop")}
              />
              <button className="tool-button danger" disabled={busy || !frameGridReady || selectedId === null} onClick={deleteSelected}>
                <span className="delete-icon" aria-hidden="true">×</span>
                <div><strong>刪除選取框</strong><small>其餘編號會自動補位</small></div>
                <kbd>DEL</kbd>
              </button>
              <button
                className="ghost-button full-width"
                disabled={busy || !frameGridReady || documentBoxes.length === 0}
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

      </aside>

      <main className="workspace">
        <div className="workspace-bar">
          <div className="document-meta">
            <strong>{currentDocument?.name || "NO DOCUMENT"}</strong>
            <span>{imageSize.width ? `${imageSize.width} × ${imageSize.height} PX` : "-- × -- PX"}</span>
          </div>
          {viewMode === "edit" ? (
            <AppearanceControls boxStyle={boxStyle} onChange={setBoxStyle} />
          ) : (
            <div className="recognition-mode-label">
              <span>{viewMode === "excel" ? "EXCEL VIEW" : "OCR VIEW"}</span>
              <strong>
                {viewMode === "excel"
                  ? `${excelResult?.format} / ${currentExcelPreview?.sheet || ""}`
                  : "辨識結果檢視"}
              </strong>
            </div>
          )}
          <p className="box-count">
            <strong>{viewMode === "excel" ? excelResult?.rows || 0 : boxes.length}</strong>
            {viewMode === "excel" ? " 筆輸出資料" : " 個裁切框"}
          </p>
        </div>

        <div
          ref={viewportRef}
          className={`canvas-viewport ${interaction?.type === "pan" ? "is-panning" : ""}`}
          onWheel={handleWheel}
        >
          {(loading || recognizing || detectingFrame || excelGenerating) && (
            <div className="loading-state" role="status">
              <LoadingArc />
              <strong>{canvasBusyTitle}</strong>
              <small>{canvasBusyDetail}</small>
            </div>
          )}
          {viewMode !== "excel" && (frameOverlayUrl || (viewMode === "recognition" && ocrResult)) && (
            <div className="recognition-toggle layer-toggle">
              {frameOverlayUrl && (
                <button
                  className={frameLayerVisible ? "active" : ""}
                  type="button"
                  onClick={() => setFrameLayerVisible((current) => !current)}
                >
                  <i className="layer-swatch frame-swatch" />
                  <span><strong>圖框 Layer</strong><small>格位座標 overlay</small></span>
                  <b>{frameLayerVisible ? "ON" : "OFF"}</b>
                </button>
              )}
              {viewMode === "recognition" && ocrResult && (
                <button
                  className={recognitionVisible ? "active" : ""}
                  type="button"
                  onClick={() => setRecognitionVisible((current) => !current)}
                >
                  <i className="layer-swatch recognition-swatch" />
                  <span><strong>OCR 標註</strong><small>螢光辨識結果</small></span>
                  <b>{recognitionVisible ? "ON" : "OFF"}</b>
                </button>
              )}
            </div>
          )}
          {viewMode === "excel" && excelResult?.previews.length > 1 && (
            <div className="excel-sheet-tabs" aria-label="Excel 工作表預覽">
              {excelResult.previews.map((preview, index) => (
                <button
                  className={index === excelPreviewIndex ? "active" : ""}
                  key={preview.sheet}
                  type="button"
                  onClick={() => {
                    if (index === excelPreviewIndex) return;
                    setExcelPreviewIndex(index);
                    setLoading(true);
                    resetView();
                  }}
                >
                  {preview.sheet}
                </button>
              ))}
            </div>
          )}
          {loadError && !loading && <div className="error-state">{loadError}</div>}
          {viewMode === "excel" && currentExcelPreview ? (
            <div
              ref={drawingSurfaceRef}
              className={`drawing-surface excel-preview-surface ${loading ? "is-loading" : ""}`}
              style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}
            >
              <img
                key={`${currentExcelPreview.file}-${excelResult.revision}`}
                src={`${currentExcelPreview.file}?revision=${excelResult.revision}`}
                alt={`${excelResult.format} ${currentExcelPreview.sheet} Excel 預覽`}
                draggable="false"
                onLoad={(event) => {
                  setImageSize({
                    width: event.currentTarget.naturalWidth,
                    height: event.currentTarget.naturalHeight,
                  });
                  setLoading(false);
                  setLoadError("");
                }}
                onError={() => {
                  setLoading(false);
                  setLoadError("Excel 預覽載入失敗");
                }}
              />
              <div
                ref={overlayRef}
                className="excel-preview-hitbox"
                onPointerDown={handleOverlayPointerDown}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
              />
            </div>
          ) : previewUrl && (
            <div
              ref={drawingSurfaceRef}
              className={`drawing-surface ${loading || recognizing || detectingFrame || excelGenerating ? "is-loading" : ""} ${viewMode === "recognition" ? "recognition-mode" : ""}`}
              style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}
            >
              <img
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
              <FrameDetectionOverlay
                revision={frameDetection?.revision}
                src={frameOverlayUrl}
                visible={frameLayerVisible}
              />
              {imageSize.width > 0 && viewMode === "edit" && frameGridReady && (
                <CropOverlay
                  activeTool={activeTool}
                  boxes={boxes}
                  boxStyle={boxStyle}
                  draft={draft}
                  imageSize={imageSize}
                  selectedId={selectedId}
                  onBoxPointerDown={handleBoxPointerDown}
                  onPointerDown={handleOverlayPointerDown}
                  onPointerLost={handlePointerLost}
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
                  results={currentOcrResults}
                  visible={recognitionVisible}
                />
              )}
            </div>
          )}
        </div>
      </main>

      <aside className="side-panel action-panel">
        <section>
          <SectionHeading step="03" eyebrow="SELECTION" title="目前選取" />
          {viewMode === "excel" ? (
            <div className="recognition-summary excel-summary">
              <strong>{excelResult?.rows || 0}</strong>
              <span>筆 {excelResult?.format} Excel 資料</span>
              <small>目前預覽：{currentExcelPreview?.sheet || "--"}</small>
            </div>
          ) : viewMode === "recognition" ? (
            <div className="recognition-summary">
              <strong>{ocrResult?.results.length || 0}</strong>
              <span>筆 OCR 辨識結果</span>
              <small>可使用工作區右上角按鈕隱藏 OCR 標註</small>
            </div>
          ) : !selectedBox ? (
            <div className="empty-card">尚未選取任何裁切框</div>
          ) : (
            <dl className="selection-details">
              <div><dt>BOX ID</dt><dd>#{String(selectedBox.id).padStart(2, "0")}</dd></div>
              <div><dt>圖框位置</dt><dd>{selectedFrameLocation || "未定位"}</dd></div>
              <div><dt>座標</dt><dd>X {Math.round(selectedBox.x)} / Y {Math.round(selectedBox.y)}</dd></div>
            </dl>
          )}
        </section>

        <section className="output-section">
          <SectionHeading step="04" eyebrow="OUTPUT" title="輸出作業" />
          <button
            className={`ghost-button full-width action-button ${hasUnsavedBoxes ? "attention" : ""}`}
            disabled={busy || !frameGridReady || documentBoxes.length === 0 || viewMode !== "edit"}
            onClick={() => submitJob("crop")}
          >儲存標註資料</button>
          <button
            className="primary-button"
            type="button"
            disabled={
              busy
              || !frameGridReady
              || documentBoxes.length === 0
              || hasUnsavedBoxes
              || !savedJobId
              || viewMode !== "edit"
            }
            title={hasUnsavedBoxes ? "裁切框有變動，請先儲存標註資料" : ""}
            onClick={submitRecognition}
          >
            <span>{recognitionButtonText}</span>
            <span aria-hidden="true">→</span>
          </button>
          {recognitionComplete && ocrResult && (
            <div className="excel-export">
              <div className="excel-export-heading">
                <span>EXCEL EXPORT</span>
                <small>根據目前 OCR 結果輸出</small>
              </div>
              <div className="excel-format-switch" aria-label="Excel 輸出格式">
                {["MIP", "QC"].map((format) => (
                  <button
                    className={format === excelFormat ? "active" : ""}
                    key={format}
                    type="button"
                    disabled={busy}
                    onClick={() => format !== excelFormat && changeExcelFormat(format)}
                  >
                    {format}
                  </button>
                ))}
              </div>
              <button
                className="primary-button excel-generate-button"
                type="button"
                disabled={busy}
                onClick={submitExcel}
              >
                <span>
                  {excelGenerating
                    ? "產生 Excel 中"
                    : excelResult
                      ? `查看 ${excelFormat} 預覽`
                      : `產生 ${excelFormat} Excel`}
                </span>
                <span aria-hidden="true">→</span>
              </button>
              {excelResult && (
                <div className="excel-result">
                  <span>✓ {excelResult.format} 已產生・{excelResult.rows} 筆</span>
                  <div>
                    <button
                      className="ghost-button"
                      type="button"
                      disabled={viewMode === "excel"}
                      onClick={() => {
                        setViewMode("excel");
                        setLoading(true);
                        resetView();
                      }}
                    >
                      返回預覽
                    </button>
                    <a className="excel-download" href={excelResult.file} download>
                      下載 Excel
                    </a>
                  </div>
                </div>
              )}
            </div>
          )}
          {jobResult && (
            <div className="job-result" key={jobResult.revision}>
              <span className="result-status">
                {jobResult.action === "crop" ? "裁切完成" : "標註已儲存"}
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
