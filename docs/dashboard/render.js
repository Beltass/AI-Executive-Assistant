// Renders the KPI dashboard HTML to a full-page PNG using the pre-installed
// Playwright Chromium. No browser download is performed.
const path = require('path');
const { execSync } = require('child_process');

const HTML = path.join(__dirname, 'cagri_merkezi_kpi_dashboard.html');
const PNG = path.join(__dirname, 'cagri_merkezi_kpi_dashboard.png');
const FILE_URL = 'file://' + HTML;

// Resolve the `playwright` (or `playwright-core`) module even when it is only
// installed in the global npm root rather than the project's node_modules.
function loadPlaywright() {
  const candidates = ['playwright', 'playwright-core'];
  for (const name of candidates) {
    try { return require(name); } catch (_) { /* try next strategy */ }
  }
  let globalRoot = '';
  try { globalRoot = execSync('npm root -g').toString().trim(); } catch (_) {}
  if (globalRoot) {
    for (const name of candidates) {
      try { return require(path.join(globalRoot, name)); } catch (_) {}
    }
  }
  throw new Error('playwright module not found (checked local + global npm root)');
}

(async () => {
  const { chromium } = loadPlaywright();

  let browser;
  try {
    browser = await chromium.launch();
  } catch (err) {
    console.error('Default launch failed, retrying with explicit executablePath:', err.message);
    browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  }

  const page = await browser.newPage({
    viewport: { width: 1300, height: 900 },
    deviceScaleFactor: 2,
  });
  await page.goto(FILE_URL, { waitUntil: 'networkidle' });
  await page.screenshot({ path: PNG, fullPage: true });
  await browser.close();

  console.log('PNG written to ' + PNG);
})().catch((err) => {
  console.error('Render failed:', err);
  process.exit(1);
});
