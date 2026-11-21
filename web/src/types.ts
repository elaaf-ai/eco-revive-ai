// Mirrors backend/app/schemas.py (API v1). Keep both in sync; tests check the contract.

export const WASTE_CLASSES = ["Plastic", "Glass", "Metal", "Organic", "Hazardous"] as const;
export type WasteClass = (typeof WASTE_CLASSES)[number];

export interface Box {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface Detection {
  id: number;
  class_id: number;
  class_name: WasteClass;
  confidence: number;
  box: Box;
}

export interface ModelInfo {
  version: string;
  status: "preview" | "released";
  format: "onnx";
  classes: WasteClass[];
  enabled_classes: WasteClass[];
}

export type QualityStatus = "ok" | "no_detections" | "low_confidence" | "ambiguous";
export type ImageHint = "too_dark" | "too_bright" | "blurry" | "small";

export interface DetectResponse {
  api_version: "1";
  request_id: string;
  model: ModelInfo;
  image: { width: number; height: number };
  detections: Detection[];
  quality: { status: QualityStatus; message: string; image_hints: ImageHint[] };
  inference_ms: number;
}

export interface GuideRequest {
  class_name: WasteClass;
  confidence: number;
  confirmed_by_user: boolean;
  item_hint?: string;
  /** 0 is the first idea; 1-9 ask the server for a different one. */
  variant?: number;
}

export interface Guide {
  class_name: WasteClass;
  kind: "upcycle" | "disposal";
  title: string;
  materials: string[];
  steps: string[];
  precautions: string[];
  source: "gemini" | "curated";
  source_detail: string;
  safety_notice: string;
}

export interface GuideResponse {
  api_version: "1";
  request_id: string;
  guide: Guide;
  cached: boolean;
}

export interface ItemSummary {
  code: string;
  name: string;
  aliases: string[];
  resin: { number: number; type: string };
}

export interface CatalogItem extends ItemSummary {
  recycling: { accepted: string; steps: string[] };
  upcycling: { title: string; materials: string[]; steps: string[]; precautions: string[] };
  safety_notice: string;
  catalog_version: string;
}

export interface Readiness {
  ready: boolean;
  model_loaded: boolean;
  model: ModelInfo | null;
  guide_provider: "gemini" | "curated_only";
  detail: string;
}
