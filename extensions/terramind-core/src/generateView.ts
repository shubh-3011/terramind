/*---------------------------------------------------------------------------------------------
 *  Copyright (c) TerraMind contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';

/**
 * Structured input captured by the Generate Infrastructure wizard, already mapped to the fields
 * that the analyzer `/v1/generate` endpoint expects.
 */
export interface GenerateWizardSubmission {
	readonly description: string;
	readonly resourceInventory: string;
	readonly connectivity: string;
	readonly constraints: string;
}

export type GenerateWizardProgressReporter = (percent: number, phase: string) => void;

export type GenerateWizardSubmitHandler = (
	submission: GenerateWizardSubmission,
	reportProgress: GenerateWizardProgressReporter
) => Promise<void>;

/**
 * Opens the guided Generate Infrastructure form. The caller owns the analyzer request and the
 * post-generation safety flow; this module only renders the form and reports status back to it.
 */
export function openGenerateWizard(
	context: vscode.ExtensionContext,
	workspaceFolder: vscode.WorkspaceFolder,
	onSubmit: GenerateWizardSubmitHandler
): vscode.WebviewPanel {
	const title = vscode.l10n.t('Generate Infrastructure');
	const panel = vscode.window.createWebviewPanel(
		'terramind.generateInfrastructureWizard',
		title,
		vscode.ViewColumn.Active,
		{
			enableScripts: true,
			retainContextWhenHidden: true,
			localResourceRoots: []
		}
	);
	panel.webview.html = getHtml(title, workspaceFolder.name);
	context.subscriptions.push(panel);

	let disposed = false;
	let submitting = false;
	panel.onDidDispose(() => {
		disposed = true;
	});

	const postStatus = (status: 'idle' | 'working' | 'success' | 'error', message: string): void => {
		if (disposed) {
			return;
		}
		void panel.webview.postMessage({ type: 'status', status, message });
	};

	panel.webview.onDidReceiveMessage(async (message: unknown) => {
		const envelope = asRecord(message);
		const type = asString(envelope.type);
		if (type === 'cancel') {
			panel.dispose();
			return;
		}
		if (type !== 'submit' || submitting) {
			return;
		}

		const payload = asRecord(envelope.payload);
		const description = asString(payload.description).trim();
		if (!description) {
			postStatus('error', vscode.l10n.t('Add a workload description before generating.'));
			return;
		}

		const rowParts: string[] = [];
		const rawRows = Array.isArray(payload.rows) ? payload.rows : [];
		for (const rawRow of rawRows) {
			const row = asRecord(rawRow);
			const kind = asString(row.kind).trim();
			const count = asString(row.count).trim();
			if (kind) {
				rowParts.push(count ? `${count} ${kind}` : kind);
			}
		}
		const inventoryText = asString(payload.inventoryText).trim();
		const resourceInventory = [rowParts.join(', '), inventoryText].filter(Boolean).join('; ');
		const connectivity = asString(payload.connectivity).trim();
		const region = asString(payload.region).trim();
		const constraintsText = asString(payload.constraints).trim();
		const constraints = [region ? vscode.l10n.t('Region: {0}', region) : '', constraintsText].filter(Boolean).join('\n');

		submitting = true;
		postStatus('working', vscode.l10n.t('Generating a Terraform draft with the configured local model.'));
		const reportProgress: GenerateWizardProgressReporter = (percent, phase) => {
			const bounded = Math.max(0, Math.min(100, Math.round(percent)));
			postStatus('working', vscode.l10n.t('Generating… {0}% · {1}', bounded, phase || 'working'));
		};
		try {
			await onSubmit({ description, resourceInventory, connectivity, constraints }, reportProgress);
			postStatus('success', vscode.l10n.t('Draft generated. Review the Terraform preview and follow the prompts.'));
		} catch (error) {
			postStatus('error', getErrorMessage(error));
		} finally {
			submitting = false;
		}
	});

	return panel;
}

function getHtml(title: string, workspaceName: string): string {
	const nonce = getNonce();
	return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'; img-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none';" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>${escapeHtml(title)}</title>
<style nonce="${nonce}">
	:root { color-scheme: light dark; }
	html {
		background: var(--vscode-editor-background, var(--vscode-sideBar-background, #ffffff));
	}
	body {
		background: var(--vscode-editor-background, var(--vscode-sideBar-background, #ffffff));
		font-family: var(--vscode-font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif);
		font-size: var(--vscode-font-size, 13px);
		color: var(--vscode-foreground, #1f1f1f);
		padding: 16px 20px 32px;
		max-width: 820px;
	}
	a { color: var(--vscode-textLink-foreground, #0a66c2); }
	h1 { font-size: 1.25em; margin: 0 0 4px; }
	p.workspace { margin: 0 0 16px; color: var(--vscode-descriptionForeground, #6a6a6a); }
	.field { margin-bottom: 16px; display: flex; flex-direction: column; gap: 6px; }
	label { font-weight: 600; }
	.hint { color: var(--vscode-descriptionForeground, #6a6a6a); font-weight: 400; }
	input[type="text"], input[type="number"], textarea {
		width: 100%;
		box-sizing: border-box;
		padding: 6px 8px;
		color: var(--vscode-input-foreground, #1f1f1f);
		background: var(--vscode-input-background, #ffffff);
		border: 1px solid var(--vscode-input-border, rgba(128, 128, 128, 0.4));
		border-radius: 2px;
		font-family: inherit;
		font-size: inherit;
	}
	input:focus, textarea:focus { outline: 1px solid var(--vscode-focusBorder, #0090f1); outline-offset: -1px; }
	textarea { resize: vertical; min-height: 64px; }
	.rows { display: flex; flex-direction: column; gap: 8px; }
	.row { display: grid; grid-template-columns: 1fr 110px auto; gap: 8px; align-items: center; }
	button { padding: 6px 12px; border: none; border-radius: 2px; cursor: pointer; font-family: inherit; font-size: inherit; }
	button:disabled { opacity: 0.6; cursor: default; }
	.primary { background: var(--vscode-button-background, #0e639c); color: var(--vscode-button-foreground, #ffffff); }
	.primary:hover:not(:disabled) { background: var(--vscode-button-hoverBackground, #1177bb); }
	.secondary {
		background: var(--vscode-button-secondaryBackground, #e0e0e0);
		color: var(--vscode-button-secondaryForeground, #1f1f1f);
		border: 1px solid var(--vscode-input-border, rgba(128, 128, 128, 0.4));
	}
	.actions { display: flex; gap: 10px; align-items: center; margin-top: 8px; }
	.status {
		margin-top: 14px;
		min-height: 20px;
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--vscode-descriptionForeground, #6a6a6a);
	}
	.status[data-state="error"] { color: var(--vscode-errorForeground, #f85149); }
	.status[data-state="success"] { color: var(--vscode-testing-iconPassed, #3fb950); }
	.spinner {
		display: none;
		width: 13px;
		height: 13px;
		border-radius: 50%;
		border: 2px solid var(--vscode-progressBar-background, #0e70c0);
		border-top-color: transparent;
		animation: spin 0.8s linear infinite;
	}
	.status.working .spinner { display: inline-block; }
	@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
	<h1>${escapeHtml(title)}</h1>
	<p class="workspace">Workspace: <strong>${escapeHtml(workspaceName)}</strong></p>
	<form id="form">
		<div class="field">
			<label for="region">Region <span class="hint">(optional, e.g. ap-south-1)</span></label>
			<input type="text" id="region" name="region" placeholder="ap-south-1" autocomplete="off" />
		</div>
		<div class="field">
			<label for="description">Workload / description <span class="hint">(required)</span></label>
			<textarea id="description" name="description" placeholder="Example: 2 private app servers in one VPC, behind a public ALB, with read-only access to one S3 bucket"></textarea>
		</div>
		<div class="field">
			<label>Resource inventory</label>
			<div class="rows" id="rows"></div>
			<div><button type="button" class="secondary" id="add-row">Add resource</button></div>
			<textarea id="inventory-text" name="inventoryText" placeholder="Optional free-text inventory. Example: 1 VPC, 2 private subnets, 1 ALB"></textarea>
		</div>
		<div class="field">
			<label for="connectivity">Connectivity / traffic flow <span class="hint">(optional)</span></label>
			<textarea id="connectivity" name="connectivity" placeholder="Example: instances live in private subnets; the ALB forwards public HTTP; instances read from the bucket; no public SSH"></textarea>
		</div>
		<div class="field">
			<label for="constraints">Constraints <span class="hint">(optional: budget, availability, security)</span></label>
			<textarea id="constraints" name="constraints" placeholder="Example: low traffic, target 99.9% availability, no fixed monthly budget, encrypt all storage"></textarea>
		</div>
		<div class="actions">
			<button type="submit" class="primary" id="generate">Generate</button>
			<button type="button" class="secondary" id="cancel">Cancel</button>
		</div>
		<div class="status" id="status" data-state="idle" role="status" aria-live="polite">
			<span class="spinner" aria-hidden="true"></span>
			<span id="status-text"></span>
		</div>
	</form>
	<script nonce="${nonce}">
		(function () {
			'use strict';
			var vscode = acquireVsCodeApi();
			var form = document.getElementById('form');
			var rows = document.getElementById('rows');
			var addRow = document.getElementById('add-row');
			var generate = document.getElementById('generate');
			var cancel = document.getElementById('cancel');
			var status = document.getElementById('status');
			var statusText = document.getElementById('status-text');

			function createRow(kind, count) {
				var row = document.createElement('div');
				row.className = 'row';
				var kindInput = document.createElement('input');
				kindInput.type = 'text';
				kindInput.className = 'row-kind';
				kindInput.placeholder = 'Resource kind (e.g. EC2 instance, S3 bucket)';
				kindInput.value = kind || '';
				var countInput = document.createElement('input');
				countInput.type = 'number';
				countInput.className = 'row-count';
				countInput.min = '1';
				countInput.step = '1';
				countInput.placeholder = 'Count';
				countInput.value = count === undefined || count === null ? '1' : String(count);
				var remove = document.createElement('button');
				remove.type = 'button';
				remove.className = 'secondary';
				remove.textContent = 'Remove';
				remove.addEventListener('click', function () { row.remove(); });
				row.appendChild(kindInput);
				row.appendChild(countInput);
				row.appendChild(remove);
				return row;
			}

			function setStatus(state, message) {
				status.setAttribute('data-state', state);
				statusText.textContent = message || '';
				if (state === 'working') {
					status.classList.add('working');
					generate.disabled = true;
				} else {
					status.classList.remove('working');
					generate.disabled = false;
				}
			}

			addRow.addEventListener('click', function () {
				var row = createRow('', '1');
				rows.appendChild(row);
				row.querySelector('.row-kind').focus();
			});

			form.addEventListener('submit', function (event) {
				event.preventDefault();
				var description = document.getElementById('description').value.trim();
				if (!description) {
					setStatus('error', 'Add a workload description before generating.');
					document.getElementById('description').focus();
					return;
				}
				var rowData = [];
				var rowElements = rows.querySelectorAll('.row');
				for (var i = 0; i < rowElements.length; i++) {
					rowData.push({
						kind: rowElements[i].querySelector('.row-kind').value,
						count: rowElements[i].querySelector('.row-count').value
					});
				}
				vscode.postMessage({
					type: 'submit',
					payload: {
						region: document.getElementById('region').value,
						description: description,
						rows: rowData,
						inventoryText: document.getElementById('inventory-text').value,
						connectivity: document.getElementById('connectivity').value,
						constraints: document.getElementById('constraints').value
					}
				});
				setStatus('working', 'Generating a Terraform draft with the configured local model...');
			});

			cancel.addEventListener('click', function () {
				vscode.postMessage({ type: 'cancel' });
			});

			window.addEventListener('message', function (event) {
				var message = event.data;
				if (!message || message.type !== 'status') {
					return;
				}
				setStatus(message.status, message.message);
			});

			rows.appendChild(createRow('', '1'));
			rows.appendChild(createRow('', '1'));
		})();
	</script>
</body>
</html>`;
}

function getNonce(): string {
	// Web-safe: works in the browser workbench and in Node/Electron.
	const bytes = new Uint8Array(16);
	globalThis.crypto.getRandomValues(bytes);
	return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
}

function asRecord(value: unknown): Record<string, unknown> {
	return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {};
}

function asString(value: unknown): string {
	return typeof value === 'string' ? value : '';
}

function escapeHtml(value: string): string {
	return value
		.replaceAll('&', '&amp;')
		.replaceAll('<', '&lt;')
		.replaceAll('>', '&gt;')
		.replaceAll('"', '&quot;')
		.replaceAll("'", '&#39;');
}

function getErrorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}
