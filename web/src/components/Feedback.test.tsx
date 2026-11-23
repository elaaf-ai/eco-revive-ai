import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import type { Detection } from "../types";
import { Feedback } from "./Feedback";

afterEach(() => vi.restoreAllMocks());

const cup: Detection = {
  id: 0,
  class_id: 0,
  class_name: "Plastic",
  confidence: 0.52,
  box: { x1: 0.1, y1: 0.1, x2: 0.5, y2: 0.6 },
  item_name: "plastic cup",
  ai_checked: true,
};

function mockSend(photoSaved: boolean) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response(JSON.stringify({ id: "f1", photo_saved: photoSaved }), { status: 200 }));
}

const sentBody = (fetchMock: ReturnType<typeof mockSend>) => JSON.parse(String(fetchMock.mock.calls[0]![1]!.body));

it("sends a yes answer without the photo unless the user agrees", async () => {
  const fetchMock = mockSend(false);
  const photo = new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: "image/jpeg" });
  render(<Feedback detection={cup} modelVersion="0.2.0" scanId="s1" photo={photo} announce={() => {}} />);
  expect(screen.getByText("Was Plastic 1 (plastic cup) right?")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Yes" }));
  const body = sentBody(fetchMock);
  expect(body).toMatchObject({ correct: true, item_name: "plastic cup", scan_id: "s1", share_photo: false });
  expect(body.image).toBeUndefined();
  expect(await screen.findByText(/Your answer will help train the next model/)).toBeInTheDocument();
});

it("sends the photo only after the share box is ticked", async () => {
  const fetchMock = mockSend(true);
  const photo = new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: "image/jpeg" });
  render(<Feedback detection={cup} modelVersion="0.2.0" photo={photo} announce={() => {}} />);
  await userEvent.click(screen.getByRole("checkbox", { name: /Share this photo/ }));
  await userEvent.click(screen.getByRole("button", { name: "No, it's wrong" }));
  const body = sentBody(fetchMock);
  expect(body).toMatchObject({ correct: false, share_photo: true, image: "/9j/" });
  expect(await screen.findByText(/Your photo and answer will help/)).toBeInTheDocument();
});

it("shows the server's message when feedback fails", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ error: { code: "history_disabled", message: "Scan history is not set up on this server." } }), {
      status: 503,
    }),
  );
  render(<Feedback detection={cup} modelVersion="0.2.0" announce={() => {}} />);
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Yes" }));
  expect(await screen.findByText("Scan history is not set up on this server.")).toBeInTheDocument();
});
