/*---------------------------------------------------------------------------------------------
 *  Copyright (c) TerraMind contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';

/**
 * Makes TerraMind self-sufficient on the desktop: opening the app is enough.
 *
 * The portable beta ships the analyzer next to the app (`<app>\analyzer`), but the
 * workbench has no idea it exists, so historically users had to run
 * `TerraMind.bat`, which downloaded the model and started uvicorn. This class moves
 * that into the extension:
 *
 *   1. if the analyzer already answers /health, do nothing;
 *   2. otherwise locate the bundled (or, from source, the dev) analyzer, start it
 *      as a child of the workbench, and wait for /health;
 *   3. if the GGUF model is missing, offer a one-time download with progress;
 *   4. surface all of it in the status bar and the TerraMind output channel.
 *
 * It never installs anything and never runs terraform.
 *
 * IMPORTANT: this file is bundled for BOTH the desktop (Node) and the browser
 * workbench. Node built-ins are therefore loaded lazily through `load()` with a
 * non-literal specifier, so esbuild's browser build never tries to resolve
 * `fs`/`https`/`child_process`. In the browser `nodeModules()` returns undefined
 * and the launcher degrades to a health check (the analyzer must be started
 * separately there).
 */

const DEFAULT_MODEL = 'terramind-qwen2.5-coder-v2-merged-Q4_K_M.gguf';
const DEFAULT_MODEL_URL =
	'https://huggingface.co/shubh-3011/terramind-qwen2.5-coder-1.5b-terraform/resolve/main/terramind-qwen2.5-coder-v2-merged-Q4_K_M.gguf';
const MIN_MODEL_BYTES = 500 * 1024 * 1024;
const HEALTH_TIMEOUT_MS = 120_000;

type FsModule = typeof import('fs');
type HttpsModule = typeof import('https');
type OsModule = typeof import('os');
type PathModule = typeof import('path');
type ChildProcessModule = typeof import('child_process');

interface NodeModules {
	readonly fs: FsModule;
	readonly https: HttpsModule;
	readonly os: OsModule;
	readonly path: PathModule;
	readonly cp: ChildProcessModule;
}

declare const require: ((id: string) => unknown) | undefined;

/** Load a Node built-in without giving esbuild a literal it could try to bundle. */
function load(id: string): unknown | undefined {
	if (typeof require !== 'function') {
		return undefined;
	}
	try {
		return (require as (specifier: string) => unknown)(id);
	} catch {
		return undefined;
	}
}

function nodeModules(): NodeModules | undefined {
	const fs = load('fs') as FsModule | undefined;
	const https = load('https') as HttpsModule | undefined;
	const os = load('os') as OsModule | undefined;
	const path = load('path') as PathModule | undefined;
	const cp = load('child_process') as ChildProcessModule | undefined;
	if (!fs || !https || !os || !path || !cp) {
		return undefined;
	}
	return { fs, https, os, path, cp };
}

interface AnalyzerLaunchSpec {
	readonly command: string;
	readonly args: readonly string[];
	readonly cwd: string;
	readonly env: NodeJS.ProcessEnv;
	readonly origin: string;
}

export interface AnalyzerLauncherOptions {
	readonly extensionPath: string;
	readonly analyzerUrl: string;
	readonly output: vscode.OutputChannel;
}

export class AnalyzerLauncher implements vscode.Disposable {
	private child: import('child_process').ChildProcess | undefined;
	private starting: Promise<boolean> | undefined;
	private readonly status: vscode.StatusBarItem;
	private readonly node = nodeModules();

	constructor(private readonly options: AnalyzerLauncherOptions) {
		this.status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
		this.status.command = 'terramind.checkAnalyzer';
		this.status.name = 'TerraMind';
		this.status.show();
		this.setStatus('$(sync~spin) TerraMind: starting', 'Starting the local analysis service…');
	}

	dispose(): void {
		this.status.dispose();
		this.stop();
	}

	/** Kill the analyzer we started (never one the user started themselves). */
	stop(): void {
		if (this.child && !this.child.killed) {
			this.options.output.appendLine('[launcher] stopping the analyzer we started');
			try {
				this.child.kill();
			} catch {
				/* best effort */
			}
		}
		this.child = undefined;
	}

	/** Directory the analyzer scans for GGUF models. */
	get modelsDirectory(): string {
		return this.modelsDir();
	}

	/** Absolute path for a model file inside the models directory ('' in the browser). */
	modelPath(id: string): string {
		return this.node ? this.node.path.join(this.modelsDir(), id) : '';
	}

	/** Whether this environment can write files (desktop) or not (browser). */
	get canDownload(): boolean {
		return Boolean(this.node);
	}

	/**
	 * Download a model file with a progress notification. Used by the model picker
	 * so a user can fetch the opt-in 7 B without leaving the app.
	 */
	async downloadModel(url: string, destination: string, label: string): Promise<boolean> {
		const fs = this.node?.fs;
		if (!fs || !this.node) {
			return false;
		}
		try {
			fs.mkdirSync(this.node.path.dirname(destination), { recursive: true });
			await vscode.window.withProgress({
				location: vscode.ProgressLocation.Notification,
				title: vscode.l10n.t('TerraMind: downloading {0}', label),
				cancellable: true,
			}, async (progress, token) => {
				const partial = `${destination}.part`;
				await this.download(url, partial, progress, token);
				fs.renameSync(partial, destination);
			});
			this.options.output.appendLine(`[launcher] downloaded ${label} to ${destination}`);
			return true;
		} catch (error) {
			this.options.output.appendLine(`[launcher] download of ${label} failed: ${String(error)}`);
			await vscode.window.showWarningMessage(vscode.l10n.t('TerraMind: the download of {0} did not finish.', label));
			return false;
		}
	}

	/** Ensure the analyzer is reachable, starting it when possible. Returns true when /health answers. */
	async ensureRunning(): Promise<boolean> {
		if (await this.isHealthy()) {
			this.setStatus('$(check) TerraMind', 'Local analysis service is running.');
			this.options.output.appendLine('[launcher] analyzer already running');
			return true;
		}
		if (!this.node) {
			this.setStatus('$(warning) TerraMind: not connected', 'Browser mode: start the TerraMind analyzer separately (run-analyzer.bat or analyzer_live.bat).');
			this.options.output.appendLine('[launcher] browser mode: cannot start the analyzer from here');
			return false;
		}
		if (!this.starting) {
			this.starting = this.startAndWait().finally(() => { this.starting = undefined; });
		}
		return this.starting;
	}

	private async startAndWait(): Promise<boolean> {
		const spec = this.resolveSpec();
		if (!spec) {
			this.setStatus('$(warning) TerraMind: analyzer missing', 'The bundled analyzer was not found. Re-extract the TerraMind ZIP.');
			this.options.output.appendLine('[launcher] no analyzer found next to the app');
			return false;
		}

		await this.ensureModel();
		this.setStatus('$(sync~spin) TerraMind: starting', `Starting ${spec.origin}…`);
		this.options.output.appendLine(`[launcher] starting analyzer from ${spec.origin}`);

		const cp = this.node!.cp;
		try {
			this.child = cp.spawn(spec.command, [...spec.args], {
				cwd: spec.cwd,
				env: spec.env,
				windowsHide: true,
				stdio: 'ignore',
			});
		} catch (error) {
			this.setStatus('$(error) TerraMind: analyzer failed', String(error));
			this.options.output.appendLine(`[launcher] spawn failed: ${String(error)}`);
			return false;
		}
		this.child.on('exit', (code, signal) => {
			this.options.output.appendLine(`[launcher] analyzer exited (code=${code ?? 'null'}, signal=${signal ?? 'none'})`);
			this.child = undefined;
			this.setStatus('$(warning) TerraMind: analyzer stopped', 'The analysis service is not running. Click to re-check.');
		});
		this.child.on('error', (error) => {
			this.options.output.appendLine(`[launcher] analyzer process error: ${String(error)}`);
		});

		const deadline = Date.now() + HEALTH_TIMEOUT_MS;
		while (Date.now() < deadline) {
			if (await this.isHealthy()) {
				this.options.output.appendLine('[launcher] analyzer is ready');
				this.setStatus('$(check) TerraMind', 'Local analysis service is running.');
				return true;
			}
			await delay(1000);
		}
		this.setStatus('$(warning) TerraMind: still starting', 'The analysis service did not answer in time. See the TerraMind output channel.');
		this.options.output.appendLine('[launcher] analyzer did not become healthy in time');
		return false;
	}

	/** Find the analyzer in the portable bundle, in the source tree, or a user setting. */
	private resolveSpec(): AnalyzerLaunchSpec | undefined {
		const path = this.node!.path;
		const fs = this.node!.fs;

		const configured = vscode.workspace.getConfiguration('terramind').get<string>('analyzerCommand', '');
		if (configured) {
			return { command: configured, args: [], cwd: path.dirname(configured), env: this.baseEnv(), origin: 'setting terramind.analyzerCommand' };
		}

		// Portable bundle: <app>\resources\app\extensions\terramind-core -> <app>
		const appRoot = path.resolve(this.options.extensionPath, '..', '..', '..', '..');
		const bundleLauncher = path.join(appRoot, 'analyzer', 'run-analyzer.bat');
		if (fs.existsSync(bundleLauncher)) {
			return {
				command: process.env.ComSpec ?? 'cmd.exe',
				args: ['/c', bundleLauncher],
				cwd: path.join(appRoot, 'analyzer'),
				env: this.baseEnv(),
				origin: bundleLauncher,
			};
		}

		// Source tree: <repo>\extensions\terramind-core -> <repo>\services\analyzer-api
		const repoRoot = path.resolve(this.options.extensionPath, '..', '..');
		const devPython = path.join(repoRoot, 'services', 'analyzer-api', '.venv', 'Scripts', 'python.exe');
		if (fs.existsSync(devPython)) {
			return {
				command: devPython,
				args: ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', this.port()],
				cwd: path.join(repoRoot, 'services', 'analyzer-api'),
				env: this.baseEnv(),
				origin: devPython,
			};
		}
		return undefined;
	}

	private baseEnv(): NodeJS.ProcessEnv {
		const path = this.node!.path;
		const fs = this.node!.fs;
		const env: NodeJS.ProcessEnv = { ...process.env, PYTHONNOUSERSITE: '1', PYTHONDONTWRITEBYTECODE: '1' };
		const modelsDir = this.modelsDir();
		env['TERRAMIND_MODELS_DIR'] = modelsDir;
		const model = path.join(modelsDir, DEFAULT_MODEL);
		if (fs.existsSync(model)) {
			env['TERRAMIND_GGUF_MODEL'] = model;
		}
		if (this.hasCudaRuntime()) {
			env['TERRAMIND_GGUF_N_GPU_LAYERS'] = '-1';
		}
		return env;
	}

	private hasCudaRuntime(): boolean {
		const path = this.node!.path;
		const fs = this.node!.fs;
		const libDir = path.join(path.resolve(this.options.extensionPath, '..', '..', '..', '..'), 'analyzer', 'runtime', 'Lib', 'site-packages', 'llama_cpp', 'lib');
		try {
			return fs.existsSync(libDir) && fs.readdirSync(libDir).some((name) => /ggml-cuda.*\.dll$/i.test(name));
		} catch {
			return false;
		}
	}

	private modelsDir(): string {
		const explicit = process.env['TERRAMIND_MODELS_DIR'];
		if (explicit) {
			return explicit;
		}
		return this.node!.path.join(this.node!.os.homedir(), '.terramind', 'models');
	}

	/** Offer a one-time download when the GGUF is missing. The analyzer and scaffolder work without it. */
	private async ensureModel(): Promise<void> {
		const fs = this.node!.fs;
		const path = this.node!.path;
		const target = path.join(this.modelsDir(), DEFAULT_MODEL);
		try {
			if (fs.statSync(target).size >= MIN_MODEL_BYTES) {
				return;
			}
		} catch {
			/* missing */
		}

		const downloadLabel = vscode.l10n.t('Download');
		const choice = await vscode.window.showInformationMessage(
			vscode.l10n.t('TerraMind needs its local AI model (about 940 MB, one time). The deterministic analyzer and scaffolder work without it. Download now?'),
			downloadLabel,
			vscode.l10n.t('Not now')
		);
		if (choice !== downloadLabel) {
			this.options.output.appendLine('[launcher] model download skipped by the user');
			return;
		}

		fs.mkdirSync(path.dirname(target), { recursive: true });
		const partial = `${target}.part`;
		try {
			await vscode.window.withProgress({
				location: vscode.ProgressLocation.Notification,
				title: vscode.l10n.t('TerraMind: downloading the local model'),
				cancellable: true,
			}, async (progress, token) => {
				await this.download(DEFAULT_MODEL_URL, partial, progress, token);
				fs.renameSync(partial, target);
			});
			this.options.output.appendLine(`[launcher] model downloaded to ${target}`);
		} catch (error) {
			this.options.output.appendLine(`[launcher] model download failed: ${String(error)}`);
			await vscode.window.showWarningMessage(vscode.l10n.t('TerraMind: the model download did not finish. You can retry, or use the deterministic scaffolder and analyzer without it.'));
		}
	}

	private download(
		url: string,
		destination: string,
		progress: vscode.Progress<{ message?: string; increment?: number }>,
		token: vscode.CancellationToken
	): Promise<void> {
		const fs = this.node!.fs;
		const https = this.node!.https;
		return new Promise<void>((resolve, reject) => {
			const request = (currentUrl: string, redirects: number): void => {
				if (redirects > 5) {
					reject(new Error('too many redirects'));
					return;
				}
				https.get(currentUrl, { headers: { 'User-Agent': 'TerraMind' } }, (response) => {
					const location = response.headers.location;
					const status = response.statusCode ?? 0;
					if (status >= 300 && status < 400 && location) {
						response.resume();
						request(new URL(location, currentUrl).toString(), redirects + 1);
						return;
					}
					if (status !== 200) {
						response.resume();
						reject(new Error(`HTTP ${status}`));
						return;
					}
					const total = Number(response.headers['content-length'] ?? 0);
					let received = 0;
					let lastPercent = 0;
					const out = fs.createWriteStream(destination);
					response.on('data', (chunk: Buffer) => {
						received += chunk.length;
						if (token.isCancellationRequested) {
							response.destroy();
							out.destroy();
							reject(new Error('cancelled'));
							return;
						}
						if (total > 0) {
							const percent = Math.floor((received / total) * 100);
							if (percent > lastPercent) {
								progress.report({ increment: percent - lastPercent, message: `${percent}%` });
								lastPercent = percent;
							}
						}
					});
					response.pipe(out);
					out.on('finish', () => out.close(() => resolve()));
					out.on('error', reject);
					response.on('error', reject);
				}).on('error', reject);
			};
			request(url, 0);
		});
	}

	private async isHealthy(): Promise<boolean> {
		try {
			const controller = new AbortController();
			const timer = setTimeout(() => controller.abort(), 1500);
			const response = await fetch(`${this.options.analyzerUrl}/health`, { signal: controller.signal });
			clearTimeout(timer);
			return response.ok;
		} catch {
			return false;
		}
	}

	private port(): string {
		try {
			return String(new URL(this.options.analyzerUrl).port || '8000');
		} catch {
			return '8000';
		}
	}

	private setStatus(text: string, tooltip: string): void {
		this.status.text = text;
		this.status.tooltip = tooltip;
	}
}

function delay(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Locate the demo workspace: shipped in the portable bundle next to the analyzer,
 * or the repository fixtures when running from source. Returns '' in the browser.
 */
export function resolveDemoFixture(extensionPath: string): string {
	const node = nodeModules();
	if (!node) {
		return '';
	}
	const { fs, path } = node;
	const appRoot = path.resolve(extensionPath, '..', '..', '..', '..');
	const bundled = path.join(appRoot, 'analyzer', 'demo-fixture');
	if (fs.existsSync(bundled)) {
		return bundled;
	}
	const repoRoot = path.resolve(extensionPath, '..', '..');
	const dev = path.join(repoRoot, 'services', 'analyzer-api', 'tests', 'fixtures', 'insecure');
	return fs.existsSync(dev) ? dev : '';
}
