import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { citation, paperRow } from "@/test/fixtures";

import { CitationViewer } from "./CitationViewer";

const destroy = vi.fn(() => Promise.resolve());
const getDocument = vi.fn(() => ({
  promise: Promise.resolve({
    destroy,
    getPage: () =>
      Promise.resolve({
        getViewport: ({ scale }: { scale: number }) => ({
          width: 612 * scale,
          height: 792 * scale,
        }),
        render: () => ({ promise: Promise.resolve() }),
      }),
  }),
}));

vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerSrc: "" },
  getDocument: (...args: unknown[]) => getDocument(...(args as [])),
}));

describe("CitationViewer", () => {
  beforeEach(() => {
    destroy.mockClear();
    getDocument.mockClear();
  });

  it("prompts for a selection when no citation is open", () => {
    render(<CitationViewer target={null} />);
    expect(screen.getByText("No passage selected")).toBeInTheDocument();
  });

  it("shows the page anchor, the match quality and the quote for a server-fetched paper", () => {
    render(
      <CitationViewer
        target={{
          row: paperRow(),
          columnLabel: "sample size",
          citation: citation(),
        }}
      />,
    );

    expect(screen.getByText("sample size")).toBeInTheDocument();
    expect(screen.getByText("page 4")).toBeInTheDocument();
    expect(screen.getByText("quote found on this page")).toBeInTheDocument();
    // The tooltip explains the match in plain words — the raw locator is one disclosure away.
    expect(
      screen.getByText("quote found on this page").parentElement,
    ).toHaveAttribute(
      "title",
      expect.stringContaining("character for character"),
    );
    const details = screen.getByText("Technical details").parentElement;
    expect(details).toHaveTextContent("text block p4-b2");
    expect(details).toHaveTextContent("match quality “exact”");
    expect(
      screen.getByText("73 patients were randomized to ziprasidone or placebo"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /open the source pdf at page 4/i }),
    ).toHaveAttribute("href", "https://example.org/paper.pdf#page=4");
  });

  it("warns when the span was only matched approximately", () => {
    render(
      <CitationViewer
        target={{
          row: paperRow(),
          columnLabel: "sample size",
          citation: citation({ match: "fuzzy" }),
        }}
      />,
    );

    expect(screen.getByText("wording is close, not exact")).toBeInTheDocument();
    expect(
      screen.getByText("wording is close, not exact").parentElement,
    ).toHaveAttribute("title", expect.stringContaining("approximate"));
    expect(
      screen.getByText("Technical details").parentElement,
    ).toHaveTextContent("match quality “fuzzy”");
  });

  it("keeps a standing caveat that locating a quote does not validate the value", () => {
    render(
      <CitationViewer
        target={{
          row: paperRow(),
          columnLabel: "sample size",
          citation: citation(),
        }}
      />,
    );

    expect(screen.getByText(/does not check the value/i)).toBeInTheDocument();
  });

  it("re-fits the page to the pane whenever the pane is resized", () => {
    const file = new File([new Uint8Array([1, 2, 3])], "paper.pdf", {
      type: "application/pdf",
    });
    let notify:
      ((entries: { contentRect: { width: number } }[]) => void) | null = null;
    const original = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      constructor(
        callback: (entries: { contentRect: { width: number } }[]) => void,
      ) {
        notify = callback;
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;

    try {
      const { container } = render(
        <CitationViewer
          target={{
            row: paperRow(),
            columnLabel: "sample size",
            citation: citation(),
          }}
          fileFor={() => file}
        />,
      );

      // Dragging the pane resizer widens the frame, and the page has to follow it: the raster
      // is fitted to the observed frame width rather than to a fixed size.
      act(() => notify?.([{ contentRect: { width: 900 } }]));
      const stack = container.querySelector(
        'div[class*="pageStack"]',
      ) as HTMLElement;
      expect(stack.style.width).toBe("900px");
    } finally {
      globalThis.ResizeObserver = original;
    }
  });

  it("opens one document per settled width and destroys it, so workers cannot pile up", async () => {
    const file = new File([new Uint8Array([1, 2, 3])], "paper.pdf", {
      type: "application/pdf",
    });
    // jsdom's File has no `arrayBuffer`, and without it the render bails before pdf.js is reached.
    Object.defineProperty(file, "arrayBuffer", {
      value: () => Promise.resolve(new ArrayBuffer(3)),
    });
    let notify:
      ((entries: { contentRect: { width: number } }[]) => void) | null = null;
    const original = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      constructor(
        callback: (entries: { contentRect: { width: number } }[]) => void,
      ) {
        notify = callback;
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
    // jsdom has no 2d context, and the render path stops short of painting without one.
    const context = vi
      .spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue({} as CanvasRenderingContext2D);
    // Nor `scrollIntoView`, which the viewer calls once the page has painted.
    HTMLElement.prototype.scrollIntoView = () => undefined;

    try {
      const { unmount } = render(
        <CitationViewer
          target={{
            row: paperRow(),
            columnLabel: "sample size",
            citation: citation(),
          }}
          fileFor={() => file}
        />,
      );

      await act(async () => notify?.([{ contentRect: { width: 625.5 } }]));
      // Sub-pixel jitter around the same layout width must not count as a new width, or every
      // wobble opens another document and its worker.
      await act(async () => notify?.([{ contentRect: { width: 625.71 } }]));
      await act(async () => notify?.([{ contentRect: { width: 625.09 } }]));
      expect(getDocument).toHaveBeenCalledTimes(1);

      await act(async () => notify?.([{ contentRect: { width: 900 } }]));
      expect(getDocument).toHaveBeenCalledTimes(2);
      expect(destroy).toHaveBeenCalledTimes(1);

      // A scrollbar appearing and leaving swings the frame by its own width, in whole pixels.
      // Returning to a width the page was already painted at must not raster it again, or the
      // swing never stops and the worker count climbs without bound.
      for (let swing = 0; swing < 5; swing += 1) {
        await act(async () => notify?.([{ contentRect: { width: 890 } }]));
        await act(async () => notify?.([{ contentRect: { width: 900 } }]));
      }
      expect(getDocument).toHaveBeenCalledTimes(3);

      unmount();
      // Every document that was opened is closed again: two superseded by a new width, one at
      // unmount.
      expect(destroy).toHaveBeenCalledTimes(3);
    } finally {
      globalThis.ResizeObserver = original;
      context.mockRestore();
    }
  });

  it("renders the page itself when the PDF was uploaded in this session", () => {
    const file = new File([new Uint8Array([1, 2, 3])], "paper.pdf", {
      type: "application/pdf",
    });
    render(
      <CitationViewer
        target={{
          row: paperRow(),
          columnLabel: "sample size",
          citation: citation(),
        }}
        fileFor={() => file}
      />,
    );

    // The quote fallback is replaced by the page surface and its highlight overlay.
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("citation-highlight")).toHaveLength(1);
  });
});
