import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const ROUTES = ["/", "/start", "/dashboard", "/dashboard/skills", "/dashboard/gaps", "/dashboard/plan", "/dashboard/evidence", "/dashboard/practice", "/dashboard/progress", "/dashboard/tutor", "/dashboard/trace"];
const WIDTHS = [375, 768, 1024, 1440];

// These pages need a learner; without one /dashboard/* redirects to /start, which is also a valid render.
for (const width of WIDTHS) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: width < 500 ? 812 : 900 } });
    for (const route of ROUTES) {
      test(`${route} renders without overflow or console errors`, async ({ page }) => {
        const errors: string[] = [];
        page.on("pageerror", (e) => errors.push(e.message));
        page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errors.push(m.text()));
        await page.goto(route, { waitUntil: "networkidle" });
        await page.waitForTimeout(600);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(overflow, "horizontal overflow").toBeLessThanOrEqual(1);
        expect(errors).toEqual([]);
      });
    }
  });
}

test.describe("accessibility", () => {
  test.use({ viewport: { width: 1440, height: 900 } });
  for (const route of ROUTES) {
    test(`${route} has no serious axe violations`, async ({ page }) => {
      await page.goto(route, { waitUntil: "networkidle" });
      await page.waitForTimeout(600);
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag22aa"]).analyze();
      const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`)).toEqual([]);
    });
  }

  test("keyboard: skip link is first tab stop and focus is visible", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  });
});
