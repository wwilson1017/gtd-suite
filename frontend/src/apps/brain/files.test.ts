// @vitest-environment node
//
// Uploading a file: the browser hashes it, reserves room with its path, size and SHA-256,
// PUTs the bytes straight to the store's link with the checksum header, then finishes it.
import { afterEach, expect, it, vi } from 'vitest';
import { size } from './FilesPage';
import { BROWSER_MAX_BYTES, sha256Hex, uploadFiles } from './api';

const STORE = 'https://store.example/cb/staging/abc?X-Amz-Signature=sig';

afterEach(() => vi.unstubAllGlobals());

it('hashes, reserves, PUTs to the store and finishes, in that order', async () => {
  const calls: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, init });
      const body =
        url === '/api/app/brain/files'
          ? {
              files: [
                {
                  id: 9,
                  upload: {
                    url: STORE,
                    headers: { 'x-amz-checksum-sha256': 'LCa0a2j/xo/5m0U8HTBBNBNCLXBkg7+g+YpeiGJm564=' },
                  },
                },
              ],
            }
          : {};
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }),
  );
  const file = new File(['foo'], 'Scan 1.pdf', { type: 'application/pdf' });
  const seen: number[] = [];
  await uploadFiles('raw/2026', [file], (n) => seen.push(n));

  expect(calls.map((c) => [c.init.method, c.url])).toEqual([
    ['POST', '/api/app/brain/files'],
    ['PUT', STORE],
    ['POST', '/api/app/brain/files/9/done'],
  ]);
  expect(JSON.parse(calls[0].init.body as string)).toEqual({
    files: [
      {
        path: 'raw/2026/Scan 1.pdf',
        size: 3,
        content_type: 'application/pdf',
        sha256: '2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae',
      },
    ],
  });
  expect(calls[1].init.headers).toEqual({ 'x-amz-checksum-sha256': 'LCa0a2j/xo/5m0U8HTBBNBNCLXBkg7+g+YpeiGJm564=' });
  expect(calls[1].init.body).toBe(file);
  expect(seen).toEqual([1]);
});

it('stops before anything is sent when the store refuses, or a file is over 500 MB', async () => {
  const fetchMock = vi.fn(
    async (url: string) =>
      new Response(
        JSON.stringify(
          url === '/api/app/brain/files' ? { files: [{ id: 9, upload: { url: STORE, headers: {} } }] } : {},
        ),
        { status: url === STORE ? 403 : 200, headers: { 'Content-Type': 'application/json' } },
      ),
  );
  vi.stubGlobal('fetch', fetchMock);
  await expect(uploadFiles('', [new File(['x'], 'a.txt')])).rejects.toThrow('Could not upload a.txt');
  expect(fetchMock.mock.calls.map(([url]) => url)).not.toContain('/api/app/brain/files/9/done');

  fetchMock.mockClear();
  const huge = new File(['x'], 'film.mov');
  Object.defineProperty(huge, 'size', { value: BROWSER_MAX_BYTES + 1 });
  await expect(uploadFiles('', [huge])).rejects.toThrow('over 500 MB');
  expect(fetchMock).not.toHaveBeenCalled();
});

it('hashes with crypto.subtle and shows sizes in decimal units', async () => {
  expect(await sha256Hex(new Blob(['']))).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
  expect([999, 1500, 2_500_000, 500_000_000, 10_000_000_000].map(size)).toEqual([
    '999 bytes',
    '1.5 KB',
    '2.5 MB',
    '500 MB',
    '10 GB',
  ]);
});

it.each(['hashing', 'between batches'])('keeps uploads on the starting brain when switching %s', async (when) => {
  const { initializeBrains, selectBrain } = await import('../todo-gtd/brainSelection');
  initializeBrains(7, [
    { id: 11, name: 'Personal', folder: 'personal', status: 'active' },
    { id: 22, name: 'Work', folder: 'work', status: 'active' },
  ]);
  selectBrain(11);
  const files = Array.from({ length: 101 }, (_, i) => new File(['x'], `${i}.txt`));
  if (when === 'hashing') {
    const read = files[0].arrayBuffer.bind(files[0]);
    files[0].arrayBuffer = async () => {
      selectBrain(22);
      return read();
    };
  }
  const calls: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      if (url === '/api/app/brain/files') {
        const items = JSON.parse(init.body as string).files as unknown[];
        return Response.json({
          files: items.map((_, i) => ({ id: i + 1, upload: { url: STORE, headers: { 'x-checksum': 'exact' } } })),
        });
      }
      return Response.json({});
    }),
  );
  await uploadFiles('', files, (n) => {
    if (when === 'between batches' && n === 100) selectBrain(22);
  });
  const app = calls.filter((c) => c.url !== STORE);
  expect(app).toHaveLength(103);
  expect(app.every((c) => new Headers(c.init.headers).get('X-Brain') === '11')).toBe(true);
  expect(
    calls
      .filter((c) => c.url === STORE)
      .every((c) => JSON.stringify(c.init.headers) === JSON.stringify({ 'x-checksum': 'exact' })),
  ).toBe(true);
});
