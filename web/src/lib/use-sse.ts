"use client";

/**
 * useWorkspaceSSE — SSE client using fetch + ReadableStream so we can
 * attach a Bearer token (EventSource doesn't support custom headers).
 *
 * Automatically reconnects on disconnect with exponential back-off.
 * Fires `onEvent` for each parsed `data:` line from the stream.
 */

import { useEffect, useRef } from "react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const MAX_BACKOFF_MS = 30_000;

export interface SSEEvent {
  type: string;
  [key: string]: unknown;
}

export function useWorkspaceSSE(
  workspaceId: string | null,
  token: string | null,
  onEvent: (event: SSEEvent) => void
) {
  const onEventRef = useRef(onEvent);
  useEffect(() => { onEventRef.current = onEvent; });

  useEffect(() => {
    if (!workspaceId || !token) return;

    let active = true;
    let attempt = 0;
    let abortController: AbortController | null = null;

    const connect = async () => {
      abortController = new AbortController();
      try {
        // The events route is workspace-scoped via the JWT claims, so the
        // path is just /events (workspaceId is not part of the URL).
        const res = await fetch(
          `${BASE}/events`,
          {
            headers: { Authorization: `Bearer ${token}` },
            signal: abortController.signal,
          }
        );

        if (!res.ok || !res.body) {
          throw new Error(`SSE connect failed: ${res.status}`);
        }

        attempt = 0; // successful connection — reset back-off
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (active) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.startsWith("data:")) continue;
            const raw = line.slice(5).trim();
            if (!raw || raw === ":keepalive") continue;
            try {
              const event = JSON.parse(raw) as SSEEvent;
              onEventRef.current(event);
            } catch {
              // non-JSON keep-alive or comment — ignore
            }
          }
        }
      } catch (err: unknown) {
        if (!active) return; // intentional teardown
        const name = (err as Error)?.name;
        if (name === "AbortError") return;
        console.warn("SSE disconnected:", err);
      }

      // Reconnect with exponential back-off
      if (!active) return;
      const delay = Math.min(500 * 2 ** attempt, MAX_BACKOFF_MS);
      attempt++;
      setTimeout(connect, delay);
    };

    connect();

    return () => {
      active = false;
      abortController?.abort();
    };
  }, [workspaceId, token]);
}
