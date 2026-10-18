// Embeds the fonts into the banner source, so the render needs no network.
import { readFileSync, writeFileSync } from "node:fs";

const here = new URL(".", import.meta.url);
const dataUri = (path, type) => `data:${type};base64,${readFileSync(new URL(path, here)).toString("base64")}`;

const html = readFileSync(new URL("banner.src.html", here), "utf8")
  .replace("__DISPLAY_FONT__", dataUri("fonts/BricolageGrotesque-latin.woff2", "font/woff2"))
  .replace("__MONO_FONT__", dataUri("fonts/JetBrainsMono-latin.woff2", "font/woff2"));

writeFileSync(new URL("banner.html", here), html);
