import type { AssetType, FileFormat, SlotStatus, StageId } from "./contract";

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDuration(ms: number | null): string {
  if (ms === null) return "-";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60_000);
  return `${minutes} min ${Math.round((ms % 60_000) / 1000)} s`;
}

export function linesToList(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

export function slotStatusLabel(status: SlotStatus): string {
  return status === "rep_unsure" ? "unsure" : status;
}

export const ASSET_LABELS: Record<AssetType, string> = {
  deck: "Deck",
  document: "Document",
  blog: "Blog post",
  email_sequence: "Email sequence",
  whitepaper: "Whitepaper",
};

export const STAGE_LABELS: Record<StageId, string> = {
  deal_brief: "Deal brief",
  retrieval: "Retrieval",
  research: "Research",
  personas: "Personas",
  strategy: "Strategy",
  assets: "Assets",
  verifier: "Verifier",
  memory_writer: "Memory writer",
  strategy_answer: "Strategy answer",
};

export const FORMAT_LABELS: Record<FileFormat, string> = {
  pptx: "PowerPoint",
  docx: "Word",
  pdf: "PDF",
  md: "Markdown",
  html: "HTML",
  eml: "Email",
};
