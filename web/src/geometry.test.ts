import { boxToPercent, fitContain, labelPlacement, scaleToMaxSide } from "./geometry";

describe("fitContain", () => {
  it("fits a landscape image into a portrait container by width", () => {
    expect(fitContain({ width: 390, height: 560 }, { width: 1280, height: 720 })).toEqual({ width: 390, height: 219 });
  });

  it("fits a portrait image into a landscape container by height", () => {
    expect(fitContain({ width: 900, height: 600 }, { width: 720, height: 1280 })).toEqual({ width: 337, height: 600 });
  });

  it("returns zero for unknown sizes", () => {
    expect(fitContain({ width: 0, height: 0 }, { width: 10, height: 10 })).toEqual({ width: 0, height: 0 });
  });
});

describe("boxToPercent", () => {
  it("converts normalized corners to CSS percentages", () => {
    expect(boxToPercent({ x1: 0.25, y1: 0.1, x2: 0.75, y2: 0.6 })).toEqual({
      left: "25.000%",
      top: "10.000%",
      width: "50.000%",
      height: "50.000%",
    });
  });

  it("clamps out-of-range values", () => {
    expect(boxToPercent({ x1: -0.2, y1: 0.5, x2: 1.4, y2: 0.4 })).toEqual({
      left: "0.000%",
      top: "50.000%",
      width: "100.000%",
      height: "0.000%",
    });
  });
});

it("places labels inside boxes that touch the top edge", () => {
  expect(labelPlacement({ x1: 0, y1: 0.02, x2: 1, y2: 1 })).toBe("inside");
  expect(labelPlacement({ x1: 0, y1: 0.3, x2: 1, y2: 1 })).toBe("above");
});

it("downscales without upscaling", () => {
  expect(scaleToMaxSide({ width: 4000, height: 3000 }, 1280)).toEqual({ width: 1280, height: 960 });
  expect(scaleToMaxSide({ width: 640, height: 480 }, 1280)).toEqual({ width: 640, height: 480 });
});
