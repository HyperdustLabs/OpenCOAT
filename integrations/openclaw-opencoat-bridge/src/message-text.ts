/** Extract / apply plain text on OpenClaw AgentMessage-shaped objects. */

export function extractAgentMessageText(message: unknown): string {
  if (!message || typeof message !== "object") return "";
  const content = (message as { content?: unknown }).content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  const parts: string[] = [];
  for (const part of content) {
    if (typeof part === "string") {
      parts.push(part);
      continue;
    }
    if (part && typeof part === "object") {
      const text = (part as { text?: unknown }).text;
      if (typeof text === "string") parts.push(text);
    }
  }
  return parts.join("");
}

export function applyAgentMessageContent(message: unknown, newText: string): unknown {
  if (!message || typeof message !== "object") return message;
  const m = message as Record<string, unknown>;
  const content = m.content;
  if (typeof content === "string") {
    return { ...m, content: newText };
  }
  if (Array.isArray(content)) {
    let replaced = false;
    const next = content.map((part) => {
      if (typeof part === "string") {
        if (!replaced) {
          replaced = true;
          return newText;
        }
        return "";
      }
      if (part && typeof part === "object") {
        const record = part as Record<string, unknown>;
        if (typeof record.text !== "string") return part;
        if (!replaced) {
          replaced = true;
          return { ...record, text: newText };
        }
        return { ...record, text: "" };
      }
      return part;
    });
    if (!next.length) return { ...m, content: [{ type: "text", text: newText }] };
    if (!replaced) return { ...m, content: [{ type: "text", text: newText }, ...next] };
    return { ...m, content: next };
  }
  return { ...m, content: newText };
}
