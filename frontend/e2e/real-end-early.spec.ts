/**
 * Real backend: ending an interview early. Costs API calls, so only with REAL_E2E=1.
 *   REAL_E2E=1 npx playwright test e2e/real-end-early.spec.ts --project=desktop
 */
import { expect, test, type Page } from "@playwright/test";

test.skip(process.env.REAL_E2E !== "1", "set REAL_E2E=1 to run against the real backend");
test.setTimeout(4 * 60_000);

async function startTypedInterview(page: Page) {
  const log: string[] = [];
  page.on("console", (m) => log.push(`console.${m.type()}: ${m.text()}`));
  page.on("pageerror", (e) => log.push(`pageerror: ${e.message}`));
  page.on("websocket", (ws) => {
    ws.on("framesent", (f) => log.push(`ws >> ${String(f.payload).slice(0, 120)}`));
    ws.on("framereceived", (f) => log.push(`ws << ${String(f.payload).slice(0, 120)}`));
    ws.on("close", () => log.push("ws closed"));
  });
  const stamp = Date.now();
  await page.goto("/#/login?signup");
  await page.getByLabel("Email").fill(`e2e-end-${stamp}@example.com`);
  await page.getByLabel("Password").fill(`e2e-pass-${stamp}`);
  await page.getByRole("button", { name: "Sign up" }).click();
  await expect(page.getByRole("heading", { name: /first mock interview/ })).toBeVisible({ timeout: 15_000 });
  await page.goto("/#/interview");
  await page.getByRole("radio", { name: "Continue without a resume" }).check();
  await page.getByRole("radio", { name: "5 min" }).click();
  await page.getByRole("radio", { name: "Type" }).click();
  await page.getByRole("button", { name: "Start interview" }).click();
  await expect(page.getByText(/Question 1 of \d+/)).toBeVisible({ timeout: 90_000 });
  return log;
}

async function endAndExpectReportLink(page: Page, log: string[]) {
  await page.getByRole("button", { name: "End interview", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/real-end-confirm.png" });
  await page.getByRole("button", { name: "Yes, end interview" }).click();
  await expect(page.getByText(/Ending the interview|Interview finished/)).toBeVisible({ timeout: 5_000 });
  try {
    await expect(page.getByRole("link", { name: "See your feedback report" })).toBeVisible({ timeout: 30_000 });
  } finally {
    console.log("STATUS:", await page.locator('[aria-live="polite"]').innerText().catch(() => "?"));
    console.log(log.slice(-25).join("\n"));
  }
}

test("end early while it's my turn", async ({ page }) => {
  const log = await startTypedInterview(page);
  await expect(page.getByLabel("Your answer")).toBeEnabled({ timeout: 60_000 });
  await endAndExpectReportLink(page, log);
});

test("end early while Asha is still thinking", async ({ page }) => {
  const log = await startTypedInterview(page);
  const answer = page.getByLabel("Your answer");
  await expect(answer).toBeEnabled({ timeout: 60_000 });
  await answer.fill("We used 512-token chunks because recall at 5 was highest on our labelled set.");
  await page.getByRole("button", { name: "Send" }).click();
  await endAndExpectReportLink(page, log); // clicked immediately, before her reply arrives
});
