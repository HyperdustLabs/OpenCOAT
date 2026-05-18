/**
 * Normalize OpenClaw chat messages for OpenCOAT COPR / JoinpointDiscovery.
 *
 * Host hooks often expose `messages[]` with OpenAI-style shapes; the runtime
 * expands them into message- and section-level joinpoints when `messages` is
 * present on the joinpoint payload.
 */

export type CoprMessageWire = {
  id?: string;
  role: string;
  content?: string;
  text?: string;
  raw_text?: string;
  sections?: Array<{ path: string; raw_text?: string }>;
};

const VALID_ROLES = new Set([
  "system",
  "developer",
  "user",
  "assistant",
  "tool",
  "memory",
  "retrieved_context",
]);

export function normalizeMessage(raw: unknown): CoprMessageWire | null {
  if (!raw || typeof raw !== "object") return null;
  const msg = raw as Record<string, unknown>;
  const roleRaw = typeof msg.role === "string" ? msg.role : "user";
  const role = VALID_ROLES.has(roleRaw) ? roleRaw : "user";
  const text = textFromMessage(msg);
  if (!text) return null;

  const out: CoprMessageWire = { role, content: text, text, raw_text: text };
  if (msg.id !== undefined && msg.id !== null) {
    out.id = String(msg.id);
  }

  const sectionsRaw = msg.sections;
  if (Array.isArray(sectionsRaw) && sectionsRaw.length) {
    const sections: Array<{ path: string; raw_text?: string }> = [];
    for (const sec of sectionsRaw) {
      if (!sec || typeof sec !== "object") continue;
      const s = sec as Record<string, unknown>;
      const path = typeof s.path === "string" ? s.path : "";
      if (!path) continue;
      const secText =
        typeof s.raw_text === "string"
          ? s.raw_text
          : typeof s.text === "string"
            ? s.text
            : undefined;
      sections.push({ path, raw_text: secText });
    }
    if (sections.length) out.sections = sections;
  }

  return out;
}

export function normalizeMessages(messages: unknown[]): CoprMessageWire[] {
  const out: CoprMessageWire[] = [];
  const slice = messages.length > 64 ? messages.slice(-64) : messages;
  for (const m of slice) {
    const norm = normalizeMessage(m);
    if (norm) out.push(norm);
  }
  return out;
}

/** Flatten messages for keyword pointcuts that still scan ``text`` / ``raw_text``. */
export function messagesToText(messages: CoprMessageWire[]): string {
  return messages
    .map((m) => m.content ?? m.text ?? m.raw_text ?? "")
    .filter(Boolean)
    .join("\n\n");
}

/**
 * Build a joinpoint payload with both legacy text fields and structured ``messages``.
 */
export function promptPayload(opts: {
  /** Extra text blobs (e.g. flattened prompt string). */
  parts?: string[];
  messages?: unknown[];
}): Record<string, unknown> {
  const normalized =
    opts.messages && Array.isArray(opts.messages)
      ? normalizeMessages(opts.messages)
      : [];

  const partText = (opts.parts ?? []).filter((p) => typeof p === "string" && p.trim());
  const messageText = normalized.length ? messagesToText(normalized) : "";
  const text = [...partText, messageText].filter(Boolean).join("\n\n");

  const payload: Record<string, unknown> = {
    text,
    raw_text: text,
    content: text,
  };

  if (normalized.length) {
    payload.messages = normalized;
  }

  return payload;
}

function textFromMessage(msg: Record<string, unknown>): string | null {
  for (const key of ["content", "text", "raw_text"]) {
    const extracted = extractText(msg[key]);
    if (extracted) return extracted;
  }
  return null;
}

function extractText(raw: unknown): string | null {
  if (typeof raw === "string") {
    const t = raw.trim();
    return t || null;
  }
  if (!Array.isArray(raw)) return null;
  const parts: string[] = [];
  for (const item of raw) {
    if (typeof item === "string" && item.trim()) {
      parts.push(item.trim());
      continue;
    }
    if (!item || typeof item !== "object") continue;
    const block = item as Record<string, unknown>;
    if (block.type === "text" && typeof block.text === "string" && block.text.trim()) {
      parts.push(block.text.trim());
    } else if (typeof block.text === "string" && block.text.trim()) {
      parts.push(block.text.trim());
    }
  }
  const joined = parts.join("\n").trim();
  return joined || null;
}
