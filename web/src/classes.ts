import type { WasteClass } from "./types";

/** Per-class colour and copy. Colours are tuned for contrast on the dark camera overlay. */
export const CLASS_META: Record<WasteClass, { color: string; short: string; blurb: string }> = {
  Plastic: { color: "#49d6c8", short: "PL", blurb: "Bottles, tubs, bags and film" },
  Glass: { color: "#a9c8ff", short: "GL", blurb: "Bottles and jars, whole or broken" },
  Metal: { color: "#e2dcef", short: "ME", blurb: "Cans, lids, foil and caps" },
  Organic: { color: "#c6f432", short: "OR", blurb: "Food scraps for compost" },
  Hazardous: { color: "#ffb020", short: "HZ", blurb: "Batteries and aerosol cans" },
};

export const percent = (value: number) => `${Math.round(value * 100)}%`;
