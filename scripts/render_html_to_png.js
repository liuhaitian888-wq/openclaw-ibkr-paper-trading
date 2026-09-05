#!/usr/bin/env node
"use strict";

const path = require("path");

async function main() {
  const args = process.argv.slice(2);
  if (args.length < 2) {
    console.error("Usage: render_html_to_png.js INPUT_HTML OUTPUT_PNG [WIDTH] [HEIGHT]");
    return 2;
  }
  const input = path.resolve(args[0]);
  const output = path.resolve(args[1]);
  const width = Number(args[2] || 1440);
  const height = Number(args[3] || 900);
  const { chromium } = require("playwright");
  const browser = await launchBrowser(chromium);
  try {
    const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
    await page.goto("file://" + input, { waitUntil: "load" });
    await page.screenshot({ path: output, fullPage: false, type: "png" });
  } finally {
    await browser.close();
  }
  return 0;
}

async function launchBrowser(chromium) {
  try {
    return await chromium.launch({ headless: true });
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    const chromeExecutable = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
    if (!message.includes("Executable doesn't exist")) {
      throw error;
    }
    return await chromium.launch({ headless: true, executablePath: chromeExecutable });
  }
}

main()
  .then((code) => process.exit(code || 0))
  .catch((error) => {
    console.error(error && error.message ? error.message : String(error));
    process.exit(1);
  });
