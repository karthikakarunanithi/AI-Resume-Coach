import { expect, test } from "@playwright/test";
import { mockApi, mockInterviewSocket } from "./mock-api";

const shot = (name: string) => ({ path: `e2e/screenshots/${name}.png`, fullPage: true });

test("landing page invites logged-out visitors in", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Practise out loud/ })).toBeVisible();
  await page.screenshot(shot("landing"));
  await page.getByRole("link", { name: /Start practising/ }).click();
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
});

test("dashboard shows stats, trend, weakest topics and history", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/");
  await expect(page.getByText("Interviews scored")).toBeVisible();
  await expect(page.getByText("+9 vs previous")).toBeVisible();
  await expect(page.getByRole("img", { name: /Overall score across 5 interviews, latest 74/ })).toBeVisible();
  await expect(page.getByRole("listitem", { name: "LLM evaluation: 41, 4 questions" })).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(5);
  await page.screenshot(shot("dashboard-light"));

  // The type filter scopes the chart and the table together
  await page.getByRole("radio", { name: "Behavioral" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(1);

  await page.emulateMedia({ colorScheme: "dark" });
  await page.getByRole("radio", { name: "All" }).click();
  await page.screenshot(shot("dashboard-dark"));
});

test("new users get an empty state, not empty charts", async ({ page }) => {
  await mockApi(page, { empty: true });
  await page.goto("/#/");
  await expect(page.getByRole("heading", { name: /first mock interview/ })).toBeVisible();
});

test("report renders scores, evidence and a stronger answer", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/report/s4");
  await expect(page.getByText("63/100", { exact: true })).toBeVisible();
  await expect(page.getByRole("listitem", { name: /Correctness: 3\.7/ })).toBeVisible();
  await expect(page.getByText("How you sounded")).toBeVisible();
  await page.getByRole("button", { name: "Show a stronger answer" }).first().click();
  await expect(page.getByText("A stronger answer", { exact: true })).toBeVisible();
  await page.screenshot(shot("report-light"));
  await page.emulateMedia({ colorScheme: "dark" });
  await page.screenshot(shot("report-dark"));
});

test("text-mode interview: setup, two answers, then the report link", async ({ page }) => {
  await mockApi(page);
  const received = await mockInterviewSocket(page);
  await page.goto("/#/interview");
  await expect(page.getByText("Karthika K")).toBeVisible(); // saved resume offered
  await page.screenshot(shot("setup"));

  await page.getByRole("radio", { name: "Type" }).click();
  await page.getByRole("button", { name: "Start interview" }).click();

  await expect(page.getByText("Question 1 of 2")).toBeVisible();
  await expect(page.getByText(/chunk size for your RAG pipeline/)).toBeVisible();
  const answer = page.getByLabel("Your answer");
  await expect(answer).toBeEnabled();
  await answer.fill("512 tokens, chosen by recall@5 on a labelled set.");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("Question 2 of 2")).toBeVisible();
  await expect(answer).toBeEnabled();
  await page.screenshot(shot("room"));
  await answer.fill("A golden set plus faithfulness scoring in CI.");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByRole("link", { name: "See your feedback report" })).toBeVisible();
  expect(received).toEqual(["512 tokens, chosen by recall@5 on a labelled set.", "A golden set plus faithfulness scoring in CI."]);
});

test("ending early asks for confirmation", async ({ page }) => {
  await mockApi(page);
  const received = await mockInterviewSocket(page);
  await page.goto("/#/interview");
  await page.getByRole("radio", { name: "Type" }).click();
  await page.getByRole("button", { name: "Start interview" }).click();
  await expect(page.getByLabel("Your answer")).toBeEnabled();
  await page.getByRole("button", { name: "End interview" }).click();
  await page.getByRole("button", { name: "Keep going" }).click();
  expect(received).toEqual([]);
  await page.getByRole("button", { name: "End interview" }).click();
  await page.getByRole("button", { name: "Yes, end interview" }).click();
  await expect(page.getByRole("link", { name: "See your feedback report" })).toBeVisible();
  expect(received).toEqual(["end_interview"]);
});

test("@mobile dashboard and report fit a phone screen", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/");
  await expect(page.getByText("Interviews scored")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  // Score and result must be on screen, not behind a sideways scroll
  const result = await page.getByRole("cell", { name: "Lean yes" }).first().boundingBox();
  expect(result!.x + result!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  await page.screenshot(shot("dashboard-mobile"));
  await page.goto("/#/report/s4");
  await expect(page.getByText("How you sounded")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  await page.screenshot(shot("report-mobile"));
});
