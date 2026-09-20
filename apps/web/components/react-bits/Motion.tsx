"use client";

// Adapted from DavidHDev/react-bits BlurText and SpotlightCard.
// Copyright (c) 2026 David Haz. See LICENSE.md in this directory.
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, type ReactNode, type PointerEvent } from "react";

export function BlurText({ text, className = "" }: { text: string; className?: string }) {
  const reduced = useReducedMotion();
  return (
    <span className={`blur-text ${className}`}>
      <span className="sr-only">{text}</span>
      <span aria-hidden="true">
        {text.split(" ").map((word, index) => (
          <motion.span
            key={`${index}-${word}`}
            className="blur-word"
            initial={false}
            whileInView={reduced ? undefined : {
              filter: ["blur(8px)", "blur(3px)", "blur(0px)"],
              opacity: [0, 0.6, 1],
              y: [14, -2, 0],
            }}
            viewport={{ once: true, amount: 0.5 }}
            transition={{ duration: 0.65, delay: index * 0.065, ease: "easeOut" }}
          >
            {word}{index < text.split(" ").length - 1 ? "\u00a0" : ""}
          </motion.span>
        ))}
      </span>
    </span>
  );
}

export function SpotlightCard({ children, className = "" }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  function move(event: PointerEvent<HTMLDivElement>) {
    if (reduced || event.pointerType !== "mouse" || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    ref.current.style.setProperty("--mouse-x", `${event.clientX - rect.left}px`);
    ref.current.style.setProperty("--mouse-y", `${event.clientY - rect.top}px`);
  }
  return <div ref={ref} onPointerMove={move} className={`card-spotlight ${className}`}>{children}</div>;
}

/** Enhance existing semantic sections without hiding content before hydration. */
export function useScrollReveals() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const root = ref.current;
    if (!root || !("IntersectionObserver" in window)) return;
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const animations = new Set<Animation>();
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        observer.unobserve(entry.target);
        if (preference.matches) continue;
        const animation = entry.target.animate([
          { opacity: 0, transform: "translateY(18px)" },
          { opacity: 1, transform: "translateY(0)" },
        ], { duration: 650, easing: "cubic-bezier(.2,.8,.3,1)" });
        animations.add(animation);
        animation.onfinish = () => animations.delete(animation);
      }
    }, { root: root.closest(".landing"), threshold: 0.12 });
    root.querySelectorAll("[data-reveal]").forEach(element => observer.observe(element));
    const stop = () => { if (preference.matches) animations.forEach(animation => animation.cancel()); };
    preference.addEventListener("change", stop);
    return () => {
      observer.disconnect();
      preference.removeEventListener("change", stop);
      animations.forEach(animation => animation.cancel());
    };
  }, []);
  return ref;
}
