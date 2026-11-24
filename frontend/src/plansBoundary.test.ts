/// <reference types="node" />
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';

const self = fileURLToPath(import.meta.url);
const source = dirname(self);
const forbidden = /\b(?:Pro|Max|pricing|Pricing|Upgrade|upgrade|billing|Billing|Stripe|stripe)\b|(['"`])(?:pro|max)\1/;

function files(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (path === join(source, 'plans') || path === self) return [];
    return entry.isDirectory() ? files(path) : [path];
  });
}

it('keeps plan vocabulary inside the plans folder', () => {
  const hits = files(source).flatMap((path) =>
    readFileSync(path, 'utf8')
      .split('\n')
      .flatMap((line, i) => (forbidden.test(line) ? [`${relative(source, path)}:${i + 1}: ${line.trim()}`] : [])),
  );
  expect(hits).toEqual([]);
});
