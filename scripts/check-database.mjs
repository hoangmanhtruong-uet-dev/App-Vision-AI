import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const venvPythonWin = resolve(root, 'backend', '.venv', 'Scripts', 'python.exe');
const venvPythonUnix = resolve(root, 'backend', '.venv', 'bin', 'python');

let pythonCmd = 'python';
if (process.platform === 'win32' && existsSync(venvPythonWin)) {
  pythonCmd = venvPythonWin;
} else if (existsSync(venvPythonUnix)) {
  pythonCmd = venvPythonUnix;
}

const script = resolve(root, 'scripts', 'check-database.py');
const result = spawnSync(pythonCmd, [script], { stdio: 'inherit', cwd: root });
process.exit(result.status ?? 0);
