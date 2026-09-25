// Browser-Test für penny.html: echter Chromium, Fake-Mikrofon, nachgebaute APIs.
// Aufruf: node tests/web/penny_html.test.mjs   (braucht das npm-Paket "playwright")
import assert from "node:assert/strict";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";
import { chromium } from "playwright";

const here = path.dirname(fileURLToPath(import.meta.url));
const PAGE = pathToFileURL(path.resolve(here, "../../penny.html")).href;
const CORS = { "access-control-allow-origin": "*", "access-control-allow-headers": "*" };

// 0,6 s Ton als 16-bit PCM (22,05 kHz)
function pcm(seconds = 0.6) {
  const n = Math.round(22050 * seconds), buf = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) buf.writeInt16LE(Math.round(Math.sin(i / 8) * 8000), i * 2);
  return buf;
}

function sse(parts, stopReason = "end_turn") {
  const ev = (type, data) => `event: ${type}\ndata: ${JSON.stringify({ type, ...data })}\n\n`;
  return ev("message_start", { message: { usage: { input_tokens: 1200, cache_read_input_tokens: 800 } } }) +
    ev("content_block_start", { index: 0, content_block: { type: "text", text: "" } }) +
    parts.map((t) => ev("content_block_delta", { index: 0, delta: { type: "text_delta", text: t } })).join("") +
    ev("content_block_stop", { index: 0 }) +
    ev("message_delta", { delta: { stop_reason: stopReason }, usage: { output_tokens: 42 } }) +
    ev("message_stop", {});
}

const browser = await chromium.launch({
  executablePath: process.env.PW_CHROMIUM || undefined,
  args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
});
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

const calls = { stt: [], claude: [], tts: [] };
const answers = [
  ["Die Special Illustration Rare liegt ", "grob bei 90 Euro. Für schnellen ", "Verkauf eher 80 Euro."],
  ["Klar, ich höre."],
];
let ttsDelay = 0;

await page.route("https://fonts.googleapis.com/**", (r) => r.fulfill({ status: 200, body: "", contentType: "text/css" }));
await page.route("https://api.elevenlabs.io/v1/speech-to-text", async (r) => {
  const req = r.request();
  calls.stt.push({ key: req.headers()["xi-api-key"], size: req.postDataBuffer()?.length || 0 });
  await r.fulfill({ status: 200, headers: CORS, contentType: "application/json", body: JSON.stringify({ text: "Was bringt ein Glurak ex?" }) });
});
await page.route("https://api.anthropic.com/v1/messages", async (r) => {
  const req = r.request();
  const body = req.postDataJSON();
  calls.claude.push({ headers: req.headers(), body });
  await r.fulfill({ status: 200, headers: CORS, contentType: "text/event-stream", body: sse(answers[Math.min(calls.claude.length - 1, answers.length - 1)]) });
});
await page.route("https://api.elevenlabs.io/v1/text-to-speech/**", async (r) => {
  const req = r.request();
  calls.tts.push({ url: req.url(), body: req.postDataJSON(), key: req.headers()["xi-api-key"] });
  if (ttsDelay) await new Promise((res) => setTimeout(res, ttsDelay));
  await r.fulfill({ status: 200, headers: CORS, contentType: "application/octet-stream", body: pcm() });
});

const state = () => page.evaluate(() => window.__penny.state);
const waitState = (s, timeout = 8000) => page.waitForFunction((x) => window.__penny.state === x, s, { timeout });

await page.goto(PAGE);

// 1) Erster Start: Einstellungen öffnen sich, Keys eintragen, speichern
assert.ok(await page.locator("#settings").evaluate((d) => d.open), "Einstellungen sollten beim ersten Start offen sein");
await page.fill("#k-anthropic", "sk-ant-test");
await page.fill("#k-eleven", "el-test");
await page.fill("#k-voice", "VOICE123");
await page.check("#k-remember");
await page.click("button[value=save]");

// 2) Starten: Begrüßung wird gesprochen
await page.click("#talk");
const until = async (fn, what, timeout = 8000) => {
  for (const end = Date.now() + timeout; !fn(); await page.waitForTimeout(50)) {
    if (Date.now() > end) throw new Error("Zeitüberschreitung: " + what);
  }
};
await until(() => calls.tts.length === 1, "Begrüßung sollte gesprochen werden");
await waitState("spricht");
await waitState("bereit");
await page.waitForFunction(() => document.querySelector("#talk").textContent.includes("Halten"));
assert.equal(calls.tts[0].body.text, "Systeme online. Ich bin bereit, Chef.");
assert.match(calls.tts[0].url, /\/VOICE123\/stream\?output_format=pcm_22050$/);
assert.equal(calls.tts[0].key, "el-test");
assert.equal(calls.tts[0].body.language_code, "de");

// 3) Sprechen per Button halten: Scribe -> Claude (Stream) -> TTS satzweise
const box = await page.locator("#talk").boundingBox();
await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
await page.mouse.down();
await waitState("hoert_zu");
await page.waitForTimeout(700);
await page.mouse.up();
await page.waitForFunction(() => window.__penny.history.length === 2, null, { timeout: 8000 });
await waitState("bereit");

assert.equal(calls.stt.length, 1);
assert.equal(calls.stt[0].key, "el-test");
assert.ok(calls.stt[0].size > 1000, "Aufnahme sollte Audio enthalten");
const c = calls.claude[0];
assert.equal(c.headers["x-api-key"], "sk-ant-test");
assert.equal(c.headers["anthropic-dangerous-direct-browser-access"], "true");
assert.equal(c.body.stream, true);
assert.equal(c.body.model, "claude-sonnet-5");
assert.deepEqual(c.body.thinking, { type: "adaptive" });
assert.deepEqual(c.body.output_config, { effort: "low" });
assert.deepEqual(c.body.messages, [{ role: "user", content: "Was bringt ein Glurak ex?" }]);
const spoken = calls.tts.slice(1).map((t) => t.body.text);
assert.deepEqual(spoken, [
  "Die Special Illustration Rare liegt grob bei 90 Euro.",
  "Für schnellen Verkauf eher 80 Euro.",
]);
assert.equal(calls.tts[2].body.previous_text, "Die Special Illustration Rare liegt grob bei 90 Euro.");
assert.match(await page.textContent("#caption"), /eher 80 Euro/);
assert.match(await page.textContent("#stats"), /1 Turns/);

// 4) Unterbrechen: Frage tippen, während Penny spricht Leertaste halten
ttsDelay = 400;
await page.fill("#ask-text", "Erzähl mir was über Displays");
await page.press("#ask-text", "Enter");
await waitState("spricht");
await page.keyboard.down(" ");
await waitState("hoert_zu");
await page.waitForTimeout(600);
await page.keyboard.up(" ");
await page.waitForFunction(() => window.__penny.history.length === 6, null, { timeout: 10000 });
await waitState("bereit");
ttsDelay = 0;
assert.equal(calls.claude.length, 3);
// Die unterbrochene Antwort ist trotzdem im Gedächtnis, bevor die nächste Frage rausgeht
assert.equal(calls.claude[2].body.messages.length, 5);
assert.equal(calls.claude[2].body.messages[3].role, "assistant");

// 5) Keys überleben ein Neuladen, Gedächtnis auch
await page.reload();
assert.ok(!(await page.locator("#settings").evaluate((d) => d.open)), "mit Keys keine Einstellungen beim Start");
assert.match(await page.textContent("#caption"), /Gedächtnis: 3 frühere Turns/);

// 6) Satz-Erkennung und Text-Säuberung wie in speech.py
const split = await page.evaluate(() => {
  const s = new window.__penny.SentenceSplitter();
  const text = "Das kostet z. B. bei Cardmarket ca. 30 Euro. Am 3. Mai kommt das neue Set.";
  const out = [];
  for (let i = 0; i < text.length; i += 3) out.push(...s.feed(text.slice(i, i + 3)));
  return out.concat(s.flush());
});
assert.deepEqual(split, ["Das kostet z. B. bei Cardmarket ca. 30 Euro.", "Am 3. Mai kommt das neue Set."]);
assert.equal(await page.evaluate(() => window.__penny.cleanForSpeech("**Glurak** kostet 45 € – super 🔥")),
  "Glurak kostet 45 Euro, super");

assert.deepEqual(errors, [], "Keine JavaScript-Fehler erwartet");
await browser.close();
console.log("penny.html: alle Browser-Tests bestanden");
