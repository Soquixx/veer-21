import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.dirname(fileURLToPath(import.meta.url));
process.chdir(root);

// Make the requested one-command startup convenient on a fresh checkout.
// Dependencies are installed only inside this frontend directory.
if (!existsSync(path.join(root, 'node_modules', 'vite'))) {
  console.log('\n[VEER-21] Frontend dependencies are missing. Installing them in frontend/ ...\n');
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const result = spawnSync(npm, ['install'], { cwd: root, stdio: 'inherit', shell: process.platform === 'win32' });
  if (result.error) {
    console.error('[VEER-21] Could not start npm. Install Node.js (20+) and npm, then run `npm install` in frontend/.');
    process.exit(1);
  }
  if (result.status !== 0) {
    console.error('[VEER-21] Dependency installation failed. Fix the npm/network error above, then run `node serve.mjs` again.');
    process.exit(result.status ?? 1);
  }
}

const { createServer } = await import('vite');
const server = await createServer({
  configFile: path.join(root, 'vite.config.js'),
  root,
  server: { host: '0.0.0.0', port: 5173, strictPort: false, open: false },
});
await server.listen();
server.printUrls();
console.log('\n[VEER-21] Frontend is running. Keep this terminal open. Press Ctrl+C to stop it.');

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, async () => {
    await server.close();
    process.exit(0);
  });
}
