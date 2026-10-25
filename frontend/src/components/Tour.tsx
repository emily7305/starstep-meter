import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { bubblePosition, markTourSeen, type Rect, type Size, TOUR_STEPS, type TourStep, tourTarget } from "../tour";

interface Props {
  open: boolean;
  onClose: () => void;
}

// how far the highlight reaches past the target
const SPOT_PAD = 6;

function sameRect(a: Rect | null, b: Rect | null): boolean {
  if (a === null || b === null) return a === b;
  return a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height;
}

function sameSize(a: Size, b: Size): boolean {
  return a.width === b.width && a.height === b.height;
}

function readTarget(id: TourStep["id"]): Rect | null {
  const box = document.querySelector(tourTarget(id))?.getBoundingClientRect();
  // a hidden element measures as an empty box, treat it like a missing one
  if (box === undefined || (box.width === 0 && box.height === 0)) return null;
  return { top: box.top, left: box.left, width: box.width, height: box.height };
}

// clientWidth leaves out the scrollbar, which fixed positioning also does
function readViewport(): Size {
  return { width: document.documentElement.clientWidth, height: document.documentElement.clientHeight };
}

// a few boxes on the page, pointed at one at a time. the state lives in the inner part so every
// opening starts at the first step
export function Tour({ open, onClose }: Props) {
  return open ? <TourSteps onClose={onClose} /> : null;
}

function TourSteps({ onClose }: { onClose: () => void }) {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const [viewport, setViewport] = useState<Size>(readViewport);
  const [bubble, setBubble] = useState<Size>({ width: 0, height: 0 });
  const bubbleRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  const step = TOUR_STEPS[index];
  const stepId = step?.id;
  const last = index === TOUR_STEPS.length - 1;

  const measure = useCallback(() => {
    const next = stepId === undefined ? null : readTarget(stepId);
    setRect((prev) => (sameRect(prev, next) ? prev : next));
    const size = readViewport();
    setViewport((prev) => (sameSize(prev, size) ? prev : size));
  }, [stepId]);

  // layout effects, so the highlight and bubble are in place before the first paint of a step
  useLayoutEffect(() => {
    if (stepId !== undefined) document.querySelector(tourTarget(stepId))?.scrollIntoView({ block: "center" });
    measure();
  }, [stepId, measure]);

  useEffect(() => {
    window.addEventListener("resize", measure);
    // capture, the timeline and the page both scroll
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [measure]);

  // the text changes the bubble's height from step to step, so it's read after every render
  useLayoutEffect(() => {
    const box = bubbleRef.current?.getBoundingClientRect();
    if (box === undefined) return;
    const size = { width: box.width, height: box.height };
    setBubble((prev) => (sameSize(prev, size) ? prev : size));
  });

  // give focus back to whatever opened the tour, so keyboard users keep their place
  useEffect(() => {
    const opener = document.activeElement;
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    nextRef.current?.focus({ preventScroll: true });
  }, [stepId]);

  const close = useCallback(() => {
    markTourSeen();
    onClose();
  }, [onClose]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [close]);

  if (step === undefined) return null;

  // moved with a transform from top 0, left 0, so its width never depends on where it sits
  const place = bubblePosition(rect, bubble, viewport);

  return (
    <>
      {rect === null ? (
        <div className="tour__dim" aria-hidden="true" />
      ) : (
        <div
          className="tour__spot"
          aria-hidden="true"
          style={{
            top: rect.top - SPOT_PAD,
            left: rect.left - SPOT_PAD,
            width: rect.width + SPOT_PAD * 2,
            height: rect.height + SPOT_PAD * 2,
          }}
        />
      )}
      <div
        ref={bubbleRef}
        className="tour"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        style={{ transform: `translate(${Math.round(place.left)}px, ${Math.round(place.top)}px)` }}
      >
        <p className="tour__count mono">{`${index + 1} / ${TOUR_STEPS.length}`}</p>
        <h2 className="tour__title" id={titleId}>
          {step.title}
        </h2>
        <p className="tour__text">{step.text}</p>
        <div className="tour__buttons">
          <button
            type="button"
            className="btn btn--outline"
            title="previous step"
            disabled={index === 0}
            onClick={() => setIndex(index - 1)}
          >
            back
          </button>
          <button
            ref={nextRef}
            type="button"
            className="btn btn--primary"
            title={last ? "close the tour" : "next step"}
            onClick={last ? close : () => setIndex(index + 1)}
          >
            {last ? "done" : "next"}
          </button>
          <button
            type="button"
            className="btn btn--link"
            title="close the tour, the ? in the header opens it again"
            onClick={close}
          >
            close tour
          </button>
        </div>
      </div>
    </>
  );
}
