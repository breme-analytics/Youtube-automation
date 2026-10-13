// Tests for panel.js: node --test panel/panel.test.cjs
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const P = require("./panel.js");

const CHANNEL = fs.readFileSync(path.join(__dirname, "..", "channel.toml"), "utf8");

test("base64 round trip keeps every character", () => {
  const text = "Ne te quæsiveris extra — “Self-Reliance” ✓";
  assert.strictEqual(P.fromBase64(P.toBase64(text)), text);
  assert.strictEqual(P.toBase64("hi"), "aGk=");
});

test("video days and minutes are read and changed in channel.toml, keeping everything else", () => {
  assert.deepStrictEqual(P.readDays(CHANNEL), ["Mon", "Thu"]);
  const changed = P.setMonthlyMinutes(P.setMakeDays(CHANNEL, ["Tue", "Sat", "Mon"]), "800");
  assert.deepStrictEqual(P.readDays(changed), ["Mon", "Tue", "Sat"]);
  assert.strictEqual(P.readSetting(changed, "monthly_minutes"), "800");
  assert.strictEqual(changed.split("\n").length, CHANNEL.split("\n").length);
  assert.ok(changed.includes("# GitHub Actions minutes this bot may use"));
  assert.throws(() => P.setMakeDays(CHANNEL, []), /at least one day/);
  assert.throws(() => P.setMakeDays(CHANNEL, ["Funday"]), /at least one day/);
  assert.throws(() => P.setMonthlyMinutes(CHANNEL, "-5"), /whole number/);
  assert.throws(() => P.setMonthlyMinutes(CHANNEL, "1.5"), /whole number/);
});

test("the books are listed in channel.toml order", () => {
  const books = P.listBooks(CHANNEL);
  assert.deepStrictEqual(books.map((b) => b.id),
    ["the-kybalion", "as-a-man-thinketh", "the-way-of-peace", "meditations", "emerson-essays"]);
  assert.strictEqual(books[0].cite, "Three Initiates, The Kybalion (1908)");
});

test("issues are sorted into waiting videos and things that need attention", () => {
  const issues = [
    { number: 1, title: "Ready to post: A", labels: [{ name: "ready-to-post" }] },
    { number: 2, title: "Scheduled: B", labels: [{ name: "scheduled" }] },
    { number: 3, title: "The bot needs a new book", labels: [{ name: "bot-needs" }] },
    { number: 4, title: "The bot needs attention: a run failed", labels: [{ name: "bot-problem" }] },
    { number: 5, title: "A pull request", labels: [{ name: "ready-to-post" }], pull_request: {} },
  ];
  assert.deepStrictEqual(P.waitingVideos(issues).map((i) => i.number), [1, 2]);
  assert.deepStrictEqual(P.attention(issues).map((i) => i.number), [3, 4]);
});

test("uploaded file names are plain and of a known kind", () => {
  assert.strictEqual(P.safeFileName("My notes.pdf"), "My-notes.pdf");
  for (const bad of ["../x.pdf", "a/b.pdf", ".env", "notes.exe", "", "x".repeat(130) + ".md"]) {
    assert.throws(() => P.safeFileName(bad), /plain name/, bad);
  }
});

test("the next video day and the monthly minutes estimate", () => {
  const status = { schedule: { make_days: ["Mon", "Thu"], run_time_utc: "03:15" } };
  const wednesday = new Date(Date.UTC(2026, 9, 14, 12, 0));
  assert.strictEqual(P.nextVideoDay(status, wednesday).toISOString(), "2026-10-15T03:15:00.000Z");
  const thursdayLate = new Date(Date.UTC(2026, 9, 15, 4, 0));
  assert.strictEqual(P.nextVideoDay(status, thursdayLate).toISOString(), "2026-10-19T03:15:00.000Z");
  assert.strictEqual(P.nextVideoDay({ schedule: { make_days: [] } }, wednesday), null);
  assert.strictEqual(P.monthlyEstimate(["Mon", "Thu"], 100), 910);  // 8.7 video days, 21.75 check-only days
});

test("the API client sends the token to GitHub only, and explains refusals", async () => {
  const seen = [];
  const fake = (url, options) => {
    seen.push({ url, options });
    if (url.endsWith("/dispatches")) return Promise.resolve({ status: 204, ok: true });
    return Promise.resolve({ status: 401, ok: false, text: () => Promise.resolve("Bad credentials") });
  };
  const client = P.makeClient(fake, "owner/repo", "TOKEN");
  await client.dispatch("produce.yml", { angle: "exam stress" });
  assert.strictEqual(seen[0].url, "https://api.github.com/repos/owner/repo/actions/workflows/produce.yml/dispatches");
  assert.strictEqual(seen[0].options.headers.Authorization, "Bearer TOKEN");
  assert.deepStrictEqual(JSON.parse(seen[0].options.body), { ref: "main", inputs: { angle: "exam stress" } });
  await assert.rejects(client.issues(), /refused the token/);
  assert.ok(seen.every((s) => s.url.startsWith("https://api.github.com/")));
});
