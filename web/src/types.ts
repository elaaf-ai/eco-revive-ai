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
  /** What the AI check sees in this box, for example "plastic cup". */
  item_name?: string | null;
  /** The AI check looked at this box and confirmed it is plastic. */
  ai_checked?: boolean;
  /** Likely resin code (the number in the recycling triangle). */
  plastic_type?: PlasticType | null;
  /** Matching item code (001-014) when the item is in the catalogue. */
  catalog_code?: string | null;
}

export interface PlasticType {
  number: number;
  type: string;
  /** False means "likely": check the number printed on the item. */
  certain: boolean;
  source: "gemini" | "catalog";
}

export interface FeedbackRequest {
  correct: boolean;
  class_name: WasteClass;
  confidence: number;
  box: Box;
  model_version: string;
  item_name?: string | null;
  scan_id?: string | null;
  share_photo: boolean;
  image?: string;
}

export interface LearningStats {
  enabled: boolean;
  feedback: number;
  correct: number;
  wrong: number;
  training_photos: number;
  model_version: string | null;
  next_step: string;
}

/** "Plastic 1", "Plastic 2" ...: detections are numbered from the most confident. */
export const itemNumber = (detection: Detection) => detection.id + 1;

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
  /** Set when the scan was saved to this browser's history. */
  scan_id?: string | null;
  /** Final plastic verdict from the detector and the Gemini vision check (captures and uploads). */
  verdict?: Verdict | null;
  /** What the AI check saw in boxes it removed as not plastic, for example "person". */
  ai_removed?: string[];
}

export interface Verdict {
  contains_plastic: boolean;
  rule: "yolo" | "gemini" | "gated";
  decided_by: "detector" | "gemini";
  detector_score: number;
  gemini: "plastic" | "no_plastic" | "unavailable" | "not_asked";
  plastic_items: string[];
  message: string;
}

export interface SavedScan {
  id: string;
  /** UTC, ISO 8601 */
  created_at: string;
  model_version: string;
  quality: QualityStatus;
  item_count: number;
  top_class: WasteClass | null;
  top_confidence: number | null;
  inference_ms: number;
  items: { class_name: WasteClass; confidence: number }[];
}

export interface ScanStats {
  scans: number;
  items_found: number;
  items_this_week?: number | null;
}

export interface HistoryResponse {
  api_version: "1";
  scans: SavedScan[];
  you: ScanStats;
  everyone: ScanStats;
}

export interface GuideRequest {
  class_name: WasteClass;
  confidence: number;
  confirmed_by_user: boolean;
  item_hint?: string;
  /** 0 is the first idea; 1-9 ask the server for a different one. */
  variant?: number;
  /** Base64 JPEG crop of the selected item, so the guide is written for that item. */
  image?: string;
  /** Plastic items the AI check saw in the whole photo, to help name the cropped item. */
  context_items?: string[];
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
  /** Item name the AI read from the image crop, for example "glasses frame". */
  identified_item?: string | null;
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
  /** True when the server has a scan history database. */
  history_enabled?: boolean;
  detail: string;
}
