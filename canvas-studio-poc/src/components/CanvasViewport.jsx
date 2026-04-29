import { useState, useEffect, useRef, useCallback } from "react";
import { Stage, Layer, Rect, Image as KImage, Transformer, Group } from "react-konva";
import Konva from "konva";

const CHECKER_SIZE = 20;
const MIN_SCALE = 0.05;
const MAX_SCALE = 4.0;

function useLoadImage(src) {
  const [img, setImg] = useState(null);
  useEffect(() => {
    if (!src) return setImg(null);
    const i = new window.Image();
    i.crossOrigin = "anonymous";
    i.onload = () => setImg(i);
    i.onerror = () => setImg(null);
    i.src = src;
    return () => { i.onload = null; };
  }, [src]);
  return img;
}

function LayerNode({ layer, selected, onSelect, onDragEnd }) {
  const img = useLoadImage(layer.image_path || layer.image_url);
  const shapeRef = useRef();
  const trRef = useRef();

  useEffect(() => {
    if (selected && trRef.current && shapeRef.current && !layer.locked) {
      trRef.current.nodes([shapeRef.current]);
      trRef.current.getLayer().batchDraw();
    }
  }, [selected, layer.locked]);

  if (!img) return null;

  const w = (layer.width || img.naturalWidth || 256) * (layer.scale || 1);
  const h = (layer.height || img.naturalHeight || 256) * (layer.scale || 1);

  return (
    <>
      <KImage
        ref={shapeRef}
        image={img}
        x={layer.x || 0}
        y={layer.y || 0}
        width={w}
        height={h}
        scaleX={1}
        scaleY={1}
        rotation={layer.rotation || 0}
        opacity={layer.opacity ?? 1}
        visible={layer.visible !== false}
        draggable={!layer.locked && selected}
        onClick={onSelect}
        onTap={onSelect}
        onDragEnd={(e) => {
          onDragEnd({
            x: Math.round(e.target.x()),
            y: Math.round(e.target.y()),
          });
        }}
      />
      {selected && !layer.locked && (
        <Transformer
          ref={trRef}
          rotateEnabled
          enabledAnchors={[
            "top-left",
            "top-right",
            "bottom-left",
            "bottom-right",
          ]}
          onTransformEnd={() => {
            const node = shapeRef.current;
            onDragEnd({
              x: Math.round(node.x()),
              y: Math.round(node.y()),
              scale: parseFloat(node.scaleX().toFixed(2)),
              rotation: parseFloat(((node.rotation() % 360 + 360) % 360).toFixed(1)),
            });
          }}
          borderStroke="#00ff88"
          anchorStroke="#00ff88"
          anchorFill="#0a0a0f"
          anchorSize={8}
        />
      )}
    </>
  );
}

export default function CanvasViewport({
  canvas,
  layers,
  selectedLayerId,
  onSelectLayer,
  onUpdateLayer,
}) {
  const containerRef = useRef();
  const [stageSize, setStageSize] = useState({ width: 800, height: 600 });
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      setStageSize({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!canvas) return;
    const sx = (stageSize.width - 40) / canvas.width;
    const sy = (stageSize.height - 40) / canvas.height;
    setScale(Math.min(sx, sy, 1));
  }, [canvas, stageSize]);

  const handleWheel = useCallback(
    (e) => {
      e.evt.preventDefault();
      const factor = e.evt.deltaY < 0 ? 1.1 : 0.9;
      setScale((s) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s * factor)));
    },
    []
  );

  if (!canvas) {
    return (
      <div ref={containerRef} className="viewport-area checkerboard">
        <div className="empty-state">
          <div className="icon">&#9670;</div>
          <h2>No canvas loaded</h2>
          <p>Create or select a canvas to begin</p>
        </div>
      </div>
    );
  }

  const sorted = [...(layers || [])].sort((a, b) => (a.z_index ?? 0) - (b.z_index ?? 0));
  const offsetX = (stageSize.width - canvas.width * scale) / 2;
  const offsetY = (stageSize.height - canvas.height * scale) / 2;

  return (
    <div ref={containerRef} className="viewport-area checkerboard">
      <Stage
        width={stageSize.width}
        height={stageSize.height}
        onWheel={handleWheel}
        onClick={(e) => {
          if (e.target === e.target.getStage()) onSelectLayer(null);
        }}
        scaleX={scale}
        scaleY={scale}
        x={offsetX}
        y={offsetY}
      >
        <Layer>
          <Rect
            x={0}
            y={0}
            width={canvas.width}
            height={canvas.height}
            fill={canvas.background_color || "#FFFFFF"}
          />
          {sorted.map((ly) => (
            <LayerNode
              key={ly.id}
              layer={ly}
              selected={ly.id === selectedLayerId}
              onSelect={() => onSelectLayer(ly.id)}
              onDragEnd={(changes) => onUpdateLayer(canvas.id, ly.id, changes)}
            />
          ))}
        </Layer>
      </Stage>
      <div
        style={{
          position: "absolute",
          bottom: 8,
          right: 8,
          background: "var(--ink-2)",
          padding: "4px 8px",
          borderRadius: 4,
          fontSize: 11,
          fontFamily: "var(--font)",
          color: "var(--text-dim)",
        }}
      >
        {Math.round(scale * 100)}%
      </div>
    </div>
  );
}
