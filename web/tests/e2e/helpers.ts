import { expect, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

export const MOCK_URL = "http://127.0.0.1:8765";
const SCREENSHOT_DIR = path.join(__dirname, "..", "..", "screenshots");
const SIZES = [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
] as const;

export async function resetMock(configure: Record<string, unknown> = {}) {
  await fetch(`${MOCK_URL}/__mock/reset`, { method: "POST" });
  if (Object.keys(configure).length > 0) await configureMock(configure);
}

export async function configureMock(config: Record<string, unknown>) {
  await fetch(`${MOCK_URL}/__mock/config`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(config),
  });
}

export async function releaseMock() {
  await fetch(`${MOCK_URL}/__mock/release`, { method: "POST" });
}

/** Saves a full-page PNG at desktop and phone widths, then restores the desktop viewport. */
export async function shoot(page: Page, name: string) {
  mkdirSync(SCREENSHOT_DIR, { recursive: true });
  for (const size of SIZES) {
    await page.setViewportSize(size);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, `${name}-${size.width}.png`), fullPage: true });
  }
  await page.setViewportSize(SIZES[0]);
}

export async function expectNoHorizontalScroll(page: Page) {
  await page.setViewportSize(SIZES[1]);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await page.setViewportSize(SIZES[0]);
}

export async function createTenant(page: Page, name = "Northwind Freight") {
  await page.getByLabel("Company name").fill(name);
  await page.getByLabel("What you sell").fill("Yard management software that cuts truck dwell time at distribution centres.");
  await page.getByLabel("Brand voice").fill("Plain, specific, no hype.");
  await page.getByLabel("Approved claims").fill("Cuts dwell time\nIntegrates with major WMS");
  await page.getByLabel("Forbidden claims").fill("Guaranteed ROI");
  await page.getByRole("button", { name: "Create tenant" }).click();
  await expect(page.getByRole("article", { name })).toBeVisible();
}

export async function startSession(page: Page, tenantName: string, account = "acme-logistics", rep = "sam-rivera") {
  const card = page.getByRole("article", { name: tenantName });
  await card.getByLabel("Account", { exact: true }).fill(account);
  await card.getByLabel("Rep", { exact: true }).fill(rep);
  await card.getByRole("button", { name: "Start interview" }).click();
  await expect(page).toHaveURL(/\/session\/[0-9a-f-]+$/);
}

export async function answer(page: Page, text: string) {
  await page.getByLabel("Type instead").fill(text);
  await page.getByRole("button", { name: "Send", exact: true }).click();
}

export async function answerUntilComplete(page: Page, count = 6) {
  const answers = [
    "Thursday at 10 with the VP of Operations",
    "A signed 12-month pilot at two sites",
    "Trucks wait too long in the yard",
    "Dwell time under 45 minutes",
    "Ops committee, then procurement",
    "The COO owns the budget",
  ];
  for (let i = 0; i < count; i++) {
    await answer(page, answers[i]);
    await expect(page.getByRole("log", { name: "Conversation" })).toContainText(answers[i]);
    // The opening turn plus one reply per answer.
    await expect(page.locator('[data-speaker="memoria"]:not([data-streaming])')).toHaveCount(i + 2);
  }
}
