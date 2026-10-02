/*---------------------------------------------------------------------------------------------
 *  Copyright (c) TerraMind contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { openGenerateWizard } from './generateView';
import { showReport } from './reportView';

export interface AnalysisResult {
	readonly terraform_file_count: number;
	readonly parsed_file_count: number;
	readonly status: string;
	readonly findings: readonly AnalysisFinding[];
	readonly risk_prediction: RiskPrediction | null;
	readonly risk_prediction_reason: string | null;
	readonly checks: Readonly<Record<string, string>>;
	readonly service_ratings: readonly ServiceRating[];
	readonly recommendations?: readonly Recommendation[];
}

export interface RatingDimension {
	readonly score: number | null;
	readonly status: string;
	readonly summary: string;
	readonly evidence?: readonly string[];
	readonly evidence_finding_ids?: readonly string[];
	readonly assumptions?: readonly string[];
	readonly limitations?: readonly string[];
}

export interface ServiceRating {
	readonly service: string;
	readonly resource_count: number;
	readonly dimensions: Readonly<Record<string, RatingDimension>>;
}

export interface Recommendation {
	readonly rule_id: string;
	readonly title: string;
	readonly severity: 'error' | 'warning' | 'information';
	readonly count: number;
	readonly priority: number;
	readonly message: string;
	readonly recommendation: string;
	readonly files?: readonly string[];
}

interface GenerationResult {
	readonly status: string;
	readonly model: string;
	readonly terraform: string;
	readonly syntax_valid: boolean;
	readonly validation_scope: string;
	readonly findings?: readonly AnalysisFinding[];
	readonly service_ratings?: readonly ServiceRating[];
	readonly recommendations?: readonly Recommendation[];
	readonly checks?: Readonly<Record<string, string>>;
}

export interface AnalysisFinding {
	readonly id: string;
	readonly source: string;
	readonly rule_id: string;
	readonly severity: 'error' | 'warning' | 'information';
	readonly message: string;
	readonly file: string;
	readonly line?: number;
	readonly recommendation?: string;
}

interface RiskPrediction {
	readonly source: string;
	readonly model_version: string;
	readonly label: string;
	readonly probability: number;
	readonly calibrated: boolean;
	readonly training_samples: number;
}

class TerraMindDashboardProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
	private readonly _onDidChangeTreeData = new vscode.EventEmitter<void>();
	readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

	private analyzerStatus = 'Analyzer Not Checked';
	private workspaceStatus = 'No Analysis Run';
	private riskStatus = 'Not Available';
	private ratingItems: readonly { readonly label: string; readonly description: string }[] = [];
	private recommendationItems: readonly { readonly label: string; readonly description: string }[] = [];

	setAnalyzerStatus(status: string): void {
		this.analyzerStatus = status;
		this._onDidChangeTreeData.fire();
	}

	refresh(
		analyzerStatus: string,
		workspaceStatus: string,
		riskStatus: string,
		ratingItems: readonly { readonly label: string; readonly description: string }[] = [],
		recommendationItems: readonly { readonly label: string; readonly description: string }[] = []
	): void {
		this.analyzerStatus = analyzerStatus;
		this.workspaceStatus = workspaceStatus;
		this.riskStatus = riskStatus;
		this.ratingItems = ratingItems;
		this.recommendationItems = recommendationItems;
		this._onDidChangeTreeData.fire();
	}

	getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
		return element;
	}

	getChildren(): vscode.TreeItem[] {
		return [
			this.createItem('TerraMind Analyzer', this.analyzerStatus, 'server'),
			this.createItem('Terraform Workspace', this.workspaceStatus, 'file-code'),
			this.createItem(vscode.l10n.t('Experimental Risk Estimate'), this.riskStatus, 'shield'),
			...this.ratingItems.map(item => this.createItem(item.label, item.description, 'graph')),
			...this.recommendationItems.map(item => this.createItem(item.label, item.description, 'lightbulb'))
		];
	}

	private createItem(label: string, description: string, icon: string): vscode.TreeItem {
		const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
		item.description = description;
		item.iconPath = new vscode.ThemeIcon(icon);
		return item;
	}
}

let sharedOutputChannel: vscode.OutputChannel | undefined;

function getOutputChannel(context: vscode.ExtensionContext): vscode.OutputChannel {
	if (!sharedOutputChannel) {
		sharedOutputChannel = vscode.window.createOutputChannel('TerraMind');
		context.subscriptions.push(sharedOutputChannel);
	}
	return sharedOutputChannel;
}

export function activate(context: vscode.ExtensionContext): void {
	const output = getOutputChannel(context);
	const diagnostics = vscode.languages.createDiagnosticCollection('terramind');
	const dashboard = new TerraMindDashboardProvider();
	context.subscriptions.push(diagnostics, vscode.window.registerTreeDataProvider('terramind.dashboard', dashboard));

	let lastReport: { readonly workspaceName: string; readonly report: AnalysisResult } | undefined;

	context.subscriptions.push(vscode.commands.registerCommand('terramind.openDashboard', async () => {
		await vscode.commands.executeCommand('workbench.view.extension.terramind');
	}));

	// Health check so the dashboard does not sit on "Analyzer Not Checked".
	const checkAnalyzer = async (notify: boolean): Promise<void> => {
		const analyzerUrl = vscode.workspace.getConfiguration('terramind').get<string>('analyzerUrl', 'http://127.0.0.1:8000');
		try {
			const response = await fetch(`${analyzerUrl}/health`);
			if (!response.ok) {
				throw new Error(`HTTP ${response.status}`);
			}
			dashboard.setAnalyzerStatus(vscode.l10n.t('Connected'));
			output.appendLine(`Analyzer health: ok (${analyzerUrl})`);
			if (notify) {
				await vscode.window.showInformationMessage(vscode.l10n.t('TerraMind analyzer is reachable at {0}.', analyzerUrl));
			}
		} catch (error) {
			dashboard.setAnalyzerStatus(vscode.l10n.t('Unavailable'));
			output.appendLine(`Analyzer health check failed: ${getErrorMessage(error)}`);
			if (notify) {
				await vscode.window.showWarningMessage(vscode.l10n.t('TerraMind analyzer is not reachable. Start the analyzer service and try again.'));
			}
		}
	};
	context.subscriptions.push(vscode.commands.registerCommand('terramind.checkAnalyzer', () => checkAnalyzer(true)));
	void checkAnalyzer(false);

	// Analyze a local fixture folder server-side. Unlike Analyze Workspace this needs
	// no browser folder picker, so it works in every browser (e.g. Brave).
	context.subscriptions.push(vscode.commands.registerCommand('terramind.analyzeDemo', async () => {
		const demoPath = vscode.workspace.getConfiguration('terramind').get<string>('demoWorkspacePath', '').trim();
		if (!demoPath) {
			await vscode.window.showErrorMessage(vscode.l10n.t('Set "terramind.demoWorkspacePath" to a local Terraform folder first.'));
			return;
		}
		try {
			const runExternalTools = vscode.workspace.getConfiguration('terramind.analysis').get<boolean>('runExternalTools', false);
			const result = await vscode.window.withProgress({
				location: vscode.ProgressLocation.Notification,
				title: vscode.l10n.t('TerraMind: Analyzing {0}', demoPath),
				cancellable: false
			}, () => requestAnalysis(demoPath, runExternalTools, false));
			lastReport = { workspaceName: demoPath, report: result };
			showReport(context, demoPath, result);
			const ratingItems = (result.service_ratings ?? []).map(rating => ({ label: `${rating.service} (${rating.resource_count})`, description: '' }));
			const recommendationItems = (result.recommendations ?? []).slice(0, 8).map(rec => ({ label: `#${rec.priority} ${rec.rule_id}`, description: rec.title || rec.message }));
			dashboard.refresh(
				vscode.l10n.t('Connected'),
				vscode.l10n.t('{0} files · {1} findings', result.terraform_file_count, result.findings.length),
				vscode.l10n.t('Demo fixture'),
				ratingItems,
				recommendationItems
			);
			for (const finding of result.findings) {
				output.appendLine(`${finding.severity.toUpperCase()} ${finding.rule_id} ${finding.file}${finding.line ? `:${finding.line}` : ''}: ${finding.message}`);
			}
			output.show(true);
			await vscode.window.showInformationMessage(vscode.l10n.t('TerraMind demo analysis: {0} finding(s) across {1} file(s). Open the Report for details.', result.findings.length, result.terraform_file_count));
		} catch (error) {
			output.appendLine(`Demo analysis failed: ${getErrorMessage(error)}`);
			output.show(true);
			await vscode.window.showErrorMessage(vscode.l10n.t('TerraMind could not analyze the demo folder. Confirm the analyzer is running.'));
		}
	}));

	context.subscriptions.push(vscode.commands.registerCommand('terramind.openReport', () => {
		const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
		showReport(context, lastReport?.workspaceName ?? workspaceFolder?.name ?? vscode.l10n.t('No workspace'), lastReport?.report);
	}));

	context.subscriptions.push(vscode.commands.registerCommand('terramind.analyzeWorkspace', async () => {
		const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
		if (!workspaceFolder) {
			await vscode.window.showErrorMessage(vscode.l10n.t('Open a Terraform workspace before starting TerraMind analysis.'));
			return;
		}

		await vscode.window.withProgress({
			location: vscode.ProgressLocation.Notification,
			title: vscode.l10n.t('TerraMind: Analyzing Terraform Workspace'),
			cancellable: false
		}, async () => {
			try {
				const runExternalTools = vscode.workspace.getConfiguration('terramind.analysis').get<boolean>('runExternalTools', false);
				const result = await requestAnalysis(workspaceFolder.uri.fsPath, runExternalTools, vscode.workspace.isTrusted);
				diagnostics.clear();
				const byFile = new Map<string, vscode.Diagnostic[]>();
				for (const finding of result.findings ?? []) {
					const segments = finding.file.replaceAll('\\', '/').split('/');
					if (finding.file.startsWith('/') || /^[A-Za-z]:/.test(finding.file) || segments.includes('..')) {
						output.appendLine(`Ignored analyzer finding with unsafe path: ${finding.file}`);
						continue;
					}
					const uri = vscode.Uri.joinPath(workspaceFolder.uri, ...segments.filter(Boolean));
					const line = Math.max(0, (finding.line ?? 1) - 1);
					const diagnostic = new vscode.Diagnostic(
						new vscode.Range(line, 0, line, 1000),
						finding.recommendation ? `${finding.message}\nRecommendation: ${finding.recommendation}` : finding.message,
						finding.severity === 'error' ? vscode.DiagnosticSeverity.Error
							: finding.severity === 'warning' ? vscode.DiagnosticSeverity.Warning
								: vscode.DiagnosticSeverity.Information
					);
					diagnostic.source = `TerraMind · ${finding.source}`;
					diagnostic.code = finding.rule_id;
					const uriKey = uri.toString();
					const existing = byFile.get(uriKey) ?? [];
					existing.push(diagnostic);
					byFile.set(uriKey, existing);
				}
				for (const [uri, fileDiagnostics] of byFile) {
					diagnostics.set(vscode.Uri.parse(uri), fileDiagnostics);
				}
				const workspaceStatus = result.terraform_file_count > 0
					? vscode.l10n.t('{0} files · {1} findings', result.terraform_file_count, result.findings.length)
					: vscode.l10n.t('No Terraform Files Found');
				const riskStatus = result.risk_prediction
					? vscode.l10n.t('{0}% · uncalibrated · n={1}', Math.round(result.risk_prediction.probability * 100), result.risk_prediction.training_samples)
					: result.risk_prediction_reason ?? vscode.l10n.t('Not Available');
				const scoredDimension = (dimension: RatingDimension | undefined, label: string): string | undefined => {
					if (!dimension || dimension.score === null || dimension.score === undefined) {
						return undefined;
					}
					return `${label} ${dimension.score}/100`;
				};
				const ratingItems = (result.service_ratings ?? []).map(rating => {
					const scores = [
						scoredDimension(rating.dimensions.security, 'security'),
						scoredDimension(rating.dimensions.reliability, 'reliability'),
						scoredDimension(rating.dimensions.maintainability, 'maintainability')
					].filter((value): value is string => Boolean(value));
					const notRated = ['security', 'reliability', 'scalability', 'cost', 'maintainability']
						.filter(dimension => rating.dimensions[dimension]?.status === 'insufficient_information');
					const description = scores.length
						? `${scores.join(' · ')}${notRated.length ? ` · ${vscode.l10n.t('not rated')}: ${notRated.join(', ')}` : ''}`
						: vscode.l10n.t('no dimension scored');
					return {
						label: `${rating.service} (${rating.resource_count})`,
						description
					};
				});
				const recommendationItems = (result.recommendations ?? []).slice(0, 8).map(recommendation => ({
					label: `#${recommendation.priority} ${recommendation.rule_id} · ${recommendation.severity}`,
					description: recommendation.title || recommendation.message
				}));
				dashboard.refresh(vscode.l10n.t('Connected'), workspaceStatus, riskStatus, ratingItems, recommendationItems);
				lastReport = { workspaceName: workspaceFolder.name, report: result };
				try {
					showReport(context, workspaceFolder.name, result);
				} catch (reportError) {
					output.appendLine(`Could not render the TerraMind report view: ${getErrorMessage(reportError)}`);
				}
				const errors = result.findings.filter(finding => finding.severity === 'error').length;
				const warnings = result.findings.filter(finding => finding.severity === 'warning').length;
				output.appendLine(`Analysis status=${result.status}; parsed=${result.parsed_file_count}/${result.terraform_file_count}; errors=${errors}; warnings=${warnings}`);
				for (const [check, status] of Object.entries(result.checks ?? {})) {
					output.appendLine(`CHECK ${check}: ${status}`);
				}
				if (runExternalTools && !vscode.workspace.isTrusted) {
					output.appendLine('External tools were skipped because this workspace is in Restricted Mode.');
				}
				for (const rating of result.service_ratings ?? []) {
					for (const [dimension, details] of Object.entries(rating.dimensions)) {
						output.appendLine(`RATING ${rating.service} ${dimension}: ${details.status}${details.score === null ? '' : ` ${details.score}/100`}; ${details.summary}`);
					}
				}
				for (const finding of result.findings) {
					output.appendLine(`${finding.severity.toUpperCase()} ${finding.rule_id} ${finding.file}${finding.line ? `:${finding.line}` : ''}: ${finding.message}`);
				}
				if (result.risk_prediction) {
					output.appendLine(`EXPERIMENTAL ML control-risk estimate=${(result.risk_prediction.probability * 100).toFixed(1)}%; samples=${result.risk_prediction.training_samples}; model=${result.risk_prediction.model_version}; calibrated=${result.risk_prediction.calibrated}`);
				}
				for (const recommendation of result.recommendations ?? []) {
					output.appendLine(`RECOMMENDATION #${recommendation.priority} [${recommendation.severity}] ${recommendation.rule_id} ×${recommendation.count}: ${recommendation.recommendation}`);
				}
				await vscode.window.showInformationMessage(vscode.l10n.t(
					'TerraMind parsed {0}/{1} Terraform files and found {2} error(s), {3} warning(s).',
					result.parsed_file_count, result.terraform_file_count, errors, warnings
				));
			} catch (error) {
				// Leave an already-open report panel untouched so a failed run neither crashes nor clears the last report.
				diagnostics.clear();
				dashboard.refresh(vscode.l10n.t('Unavailable'), vscode.l10n.t('Analysis Not Run'), vscode.l10n.t('Not Available'));
				output.appendLine(`Analyzer request failed: ${getErrorMessage(error)}`);
				output.show(true);
				await vscode.window.showErrorMessage(vscode.l10n.t('TerraMind could not reach the local analyzer. Start the analyzer service and try again.'));
			}
		});
	}));

	context.subscriptions.push(vscode.commands.registerCommand('terramind.generateInfrastructure', async () => {
		const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
		if (!workspaceFolder) {
			await vscode.window.showErrorMessage(vscode.l10n.t('Open a workspace before generating Terraform.'));
			return;
		}
		const requirements = await vscode.window.showInputBox({
			prompt: vscode.l10n.t('Describe the AWS infrastructure and how resources connect.'),
			placeHolder: vscode.l10n.t('Example: 2 private app servers in one VPC, behind a public ALB, with read-only access to one S3 bucket'),
			ignoreFocusOut: true
		});
		if (!requirements?.trim()) {
			return;
		}
		const resourceInventory = await vscode.window.showInputBox({
			prompt: vscode.l10n.t('List resource types and desired counts. This field is optional.'),
			placeHolder: vscode.l10n.t('Example: 2 EC2 instances, 1 VPC, 1 S3 bucket'),
			ignoreFocusOut: true
		});
		const connectivity = await vscode.window.showInputBox({
			prompt: vscode.l10n.t('Describe how resources should connect and how traffic should flow. This field is optional.'),
			placeHolder: vscode.l10n.t('Example: both instances in private subnets; instances read from the bucket; no public SSH'),
			ignoreFocusOut: true
		});
		const constraints = await vscode.window.showInputBox({
			prompt: vscode.l10n.t('Add region, traffic, budget, availability, and security constraints.'),
			placeHolder: vscode.l10n.t('Example: ap-south-1, low traffic, target 99.9% availability; no fixed monthly budget'),
			ignoreFocusOut: true
		});
		try {
			const model = vscode.workspace.getConfiguration('terramind').get<string>('generationModel', 'qwen2.5-coder:3b');
			const runExternalTools = vscode.workspace.getConfiguration('terramind.analysis').get<boolean>('runExternalTools', false);
			const generated = await requestGenerationJob(
				requirements.trim(),
				resourceInventory?.trim() ?? '',
				connectivity?.trim() ?? '',
				constraints?.trim() ?? '',
				model,
				workspaceFolder.uri.fsPath,
				runExternalTools,
				vscode.workspace.isTrusted
			);
			if (!generated) {
				return;
			}
			await presentGeneratedDraft(context, workspaceFolder, generated);
		} catch (error) {
			output.appendLine(`Local Terraform generation failed: ${getErrorMessage(error)}`);
			output.show(true);
			await vscode.window.showErrorMessage(vscode.l10n.t('TerraMind could not generate a draft. Confirm the local analyzer and configured model backend are available.'));
		}
	}));

	context.subscriptions.push(vscode.commands.registerCommand('terramind.generateInfrastructureWizard', async () => {
		const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
		if (!workspaceFolder) {
			await vscode.window.showErrorMessage(vscode.l10n.t('Open a workspace before generating Terraform.'));
			return;
		}
		openGenerateWizard(context, workspaceFolder, async (submission, reportProgress) => {
			const model = vscode.workspace.getConfiguration('terramind').get<string>('generationModel', 'qwen2.5-coder:3b');
			const runExternalTools = vscode.workspace.getConfiguration('terramind.analysis').get<boolean>('runExternalTools', false);
			const generated = await requestGenerationJob(
				submission.description,
				submission.resourceInventory,
				submission.connectivity,
				submission.constraints,
				model,
				workspaceFolder.uri.fsPath,
				runExternalTools,
				vscode.workspace.isTrusted,
				reportProgress
			);
			if (!generated) {
				return;
			}
			// Resolve the wizard as soon as the draft exists so its Generate button
			// re-enables; preview/save/analysis then proceed independently.
			void presentGeneratedDraft(context, workspaceFolder, generated);
		});
	}));

	context.subscriptions.push(vscode.commands.registerCommand('terramind.proposeRepair', async () => {
		const editor = vscode.window.activeTextEditor;
		const workspaceFolder = editor && vscode.workspace.getWorkspaceFolder(editor.document.uri);
		if (!editor || !workspaceFolder || editor.document.languageId !== 'terraform' || !editor.document.uri.path.toLowerCase().endsWith('.tf')) {
			await vscode.window.showErrorMessage(vscode.l10n.t('Open a Terraform .tf file in the current workspace before proposing a repair.'));
			return;
		}
		if (editor.document.uri.scheme !== 'file') {
			await vscode.window.showErrorMessage(vscode.l10n.t('TerraMind repair proposals are available for local workspace files only.'));
			return;
		}
		if (editor.document.isDirty) {
			const saveChoice = await vscode.window.showInformationMessage(
				vscode.l10n.t('Save the current Terraform file before preparing a repair proposal?'),
				{ modal: true }, vscode.l10n.t('Save and Continue'), vscode.l10n.t('Cancel')
			);
			if (saveChoice !== vscode.l10n.t('Save and Continue') || !await editor.document.save()) {
				return;
			}
		}
		const instructions = await vscode.window.showInputBox({
			prompt: vscode.l10n.t('Optional: describe the change you want. TerraMind will propose a diff and will not edit until you approve it.'),
			placeHolder: vscode.l10n.t('Example: restrict SSH ingress to the office CIDR'),
			ignoreFocusOut: true
		});
		if (instructions === undefined) {
			return;
		}

		const document = editor.document;
		const originalText = document.getText();
		const originalVersion = document.version;
		const findings = vscode.languages.getDiagnostics(document.uri)
			.filter(diagnostic => diagnostic.source?.startsWith('TerraMind'))
			.slice(0, 50)
			.map(diagnostic => `${diagnostic.code ?? 'finding'}: ${diagnostic.message}`);
		try {
			const model = vscode.workspace.getConfiguration('terramind').get<string>('generationModel', 'qwen2.5-coder:3b');
			const runExternalTools = vscode.workspace.getConfiguration('terramind.analysis').get<boolean>('runExternalTools', false);
			const proposal = await vscode.window.withProgress({
				location: vscode.ProgressLocation.Notification,
				title: vscode.l10n.t('TerraMind: Preparing a Terraform repair proposal'),
				cancellable: false
			}, () => requestRepair(
				originalText, findings, instructions.trim(), model, workspaceFolder.uri.fsPath,
				runExternalTools, vscode.workspace.isTrusted
			));
			const proposalErrors = (proposal.findings ?? []).filter(finding => finding.severity === 'error').length;
			const proposalWarnings = (proposal.findings ?? []).filter(finding => finding.severity === 'warning').length;
			output.appendLine(`Repair proposal from ${proposal.model}: errors=${proposalErrors}; warnings=${proposalWarnings}; ${proposal.validation_scope}`);
			for (const finding of proposal.findings ?? []) {
				output.appendLine(`${finding.severity.toUpperCase()} ${finding.rule_id} ${finding.file}${finding.line ? `:${finding.line}` : ''}: ${finding.message}`);
			}
			output.show(true);
			const preview = await vscode.workspace.openTextDocument({ language: 'terraform', content: proposal.terraform });
			await vscode.commands.executeCommand(
				'vscode.diff', document.uri, preview.uri,
				vscode.l10n.t('TerraMind Repair Proposal: {0}', vscode.workspace.asRelativePath(document.uri)),
				{ preview: true }
			);
			const choice = await vscode.window.showInformationMessage(
				vscode.l10n.t('Review the diff. HCL parsing passed; static/CLI checks found {0} error(s) and {1} warning(s). Provider check: {2}. Apply this replacement?', proposalErrors, proposalWarnings, proposal.checks?.terraform_validate ?? vscode.l10n.t('not run')),
				{ modal: true }, vscode.l10n.t('Apply Repair'), vscode.l10n.t('Discard Proposal')
			);
			if (choice !== vscode.l10n.t('Apply Repair')) {
				return;
			}
			if (document.version !== originalVersion || document.getText() !== originalText) {
				await vscode.window.showErrorMessage(vscode.l10n.t('The Terraform file changed while the repair was being reviewed. The proposal was not applied; run it again.'));
				return;
			}
			const edit = new vscode.WorkspaceEdit();
			edit.replace(document.uri, new vscode.Range(document.positionAt(0), document.positionAt(originalText.length)), proposal.terraform);
			if (!await vscode.workspace.applyEdit(edit)) {
				throw new Error('VS Code declined the approved workspace edit.');
			}
			if (!await document.save()) {
				await vscode.window.showWarningMessage(vscode.l10n.t('The approved repair remains unsaved. Save the file manually before running workspace analysis.'));
				return;
			}
			output.appendLine(`Applied user-approved repair proposal to ${vscode.workspace.asRelativePath(document.uri)}; re-running workspace analysis.`);
			output.show(true);
			await vscode.commands.executeCommand('terramind.analyzeWorkspace');
		} catch (error) {
			output.appendLine(`Terraform repair proposal failed: ${getErrorMessage(error)}`);
			output.show(true);
			await vscode.window.showErrorMessage(vscode.l10n.t('TerraMind could not prepare a repair proposal. Confirm the local analyzer and configured model backend are available.'));
		}
	}));
}

/**
 * Reviews a generated draft through the same safety flow for every entry point: preview the HCL,
 * log findings/ratings/checks, confirm before writing, then re-run workspace analysis.
 */
export async function presentGeneratedDraft(
	context: vscode.ExtensionContext,
	workspaceFolder: vscode.WorkspaceFolder,
	generated: GenerationResult
): Promise<void> {
	if (!generated.syntax_valid) {
		throw new Error('The generated draft did not pass HCL syntax parsing.');
	}
	const output = getOutputChannel(context);
	if (!generated.terraform.trim()) {
		output.appendLine('Generation returned an empty Terraform draft; refusing to preview or save it.');
		output.show(true);
		await vscode.window.showErrorMessage(vscode.l10n.t('TerraMind generated an empty Terraform draft. Nothing was saved; adjust the description and run generation again.'));
		return;
	}
	output.appendLine(`Generated Terraform draft with ${generated.model}. ${generated.validation_scope}`);
	const findings = generated.findings ?? [];
	for (const [check, status] of Object.entries(generated.checks ?? {})) {
		output.appendLine(`GENERATED CHECK ${check}: ${status}`);
	}
	const errors = findings.filter(finding => finding.severity === 'error').length;
	const warnings = findings.filter(finding => finding.severity === 'warning').length;
	for (const finding of findings) {
		output.appendLine(`${finding.severity.toUpperCase()} ${finding.rule_id} ${finding.file}${finding.line ? `:${finding.line}` : ''}: ${finding.message}`);
	}
	for (const rating of generated.service_ratings ?? []) {
		for (const [dimension, details] of Object.entries(rating.dimensions)) {
			output.appendLine(`GENERATED RATING ${rating.service} ${dimension}: ${details.status}${details.score === null ? '' : ` ${details.score}/100`}; ${details.summary}`);
		}
	}
	for (const recommendation of generated.recommendations ?? []) {
		output.appendLine(`GENERATED RECOMMENDATION #${recommendation.priority} [${recommendation.severity}] ${recommendation.rule_id} ×${recommendation.count}: ${recommendation.recommendation}`);
	}
	output.show(true);
	const preview = await vscode.workspace.openTextDocument({ language: 'terraform', content: generated.terraform });
	await vscode.window.showTextDocument(preview, { preview: false });
	const providerValidation = generated.checks?.terraform_validate ?? vscode.l10n.t('not_run: no validation status returned');
	const choice = await vscode.window.showInformationMessage(
		vscode.l10n.t('Draft parsed as HCL; static/CLI checks found {0} error(s) and {1} warning(s). Terraform validate: {2}. Cost, runtime availability, and deployment behavior are not verified.', errors, warnings, providerValidation),
		{ modal: true },
		vscode.l10n.t('Save Draft to Workspace'),
		vscode.l10n.t('Discard')
	);
	if (choice !== vscode.l10n.t('Save Draft to Workspace')) {
		return;
	}
	const defaultTarget = vscode.Uri.joinPath(workspaceFolder.uri, 'terramind-generated', 'main.tf');
	const target = await vscode.window.showSaveDialog({
		defaultUri: defaultTarget,
		saveLabel: vscode.l10n.t('Save Reviewed Terraform Draft'),
		filters: { [vscode.l10n.t('Terraform')]: ['tf'] }
	});
	if (!target) {
		return;
	}
	if (vscode.workspace.getWorkspaceFolder(target)?.uri.toString() !== workspaceFolder.uri.toString()) {
		await vscode.window.showErrorMessage(vscode.l10n.t('Choose a location inside the currently open workspace.'));
		return;
	}
	let exists = false;
	try {
		await vscode.workspace.fs.stat(target);
		exists = true;
	} catch (error) {
		if (!(error instanceof vscode.FileSystemError) || error.code !== 'FileNotFound') {
			throw error;
		}
	}
	if (exists) {
		const overwrite = await vscode.window.showWarningMessage(
			vscode.l10n.t('This file already exists. Replace it with the reviewed draft?'),
			{ modal: true }, vscode.l10n.t('Overwrite')
		);
		if (overwrite !== vscode.l10n.t('Overwrite')) {
			return;
		}
	}
	try {
		await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(target, '..'));
		await vscode.workspace.fs.writeFile(target, new TextEncoder().encode(generated.terraform));
		// Re-analyze in the background; do not block the wizards's completion on it.
		const written = await vscode.workspace.fs.stat(target);
		if (!written || written.size <= 0) {
			output.appendLine(`ERROR: wrote empty file at ${describeUri(target)} (reported ${written ? written.size : 'unknown'} bytes). The draft was not persisted.`);
			output.show(true);
			await vscode.window.showErrorMessage(vscode.l10n.t('TerraMind saved the draft at {0} but the file is empty on disk. Nothing usable was written; check the workspace file system and try again.', describeUri(target)));
			return;
		}
		output.appendLine(`Saved reviewed draft to ${describeUri(target)} (${written.size} bytes); starting workspace analysis.`);
		output.show(true);
		const savedDocument = await vscode.workspace.openTextDocument(target);
		await vscode.window.showTextDocument(savedDocument, { preview: false });
		await closeUntitledDocument(preview);
		void vscode.commands.executeCommand('terramind.analyzeWorkspace');
	} catch (error) {
		output.appendLine(`Saving the reviewed draft to ${describeUri(target)} failed: ${getErrorMessage(error)}`);
		output.show(true);
		await vscode.window.showErrorMessage(vscode.l10n.t('TerraMind could not save the draft to {0}: {1}', describeUri(target), getErrorMessage(error)));
	}
}

/** Returns a human-readable absolute location for logging and messages. */
function describeUri(uri: vscode.Uri): string {
	return uri.scheme === 'file' ? uri.fsPath : uri.toString();
}

/** Closes the untitled generation preview so the user is left looking at the saved file. */
async function closeUntitledDocument(document: vscode.TextDocument): Promise<void> {
	if (!document.isUntitled) {
		return;
	}
	try {
		const previewTabs = vscode.window.tabGroups.all
			.flatMap(group => group.tabs)
			.filter(tab => tab.input instanceof vscode.TabInputText && tab.input.uri.toString() === document.uri.toString());
		if (previewTabs.length) {
			await vscode.window.tabGroups.close(previewTabs);
		}
	} catch {
		// Best effort only: leaving the untitled preview open is harmless.
	}
}

/** fetch with an AbortController timeout so a stalled analyzer cannot hang the UI. */
async function fetchWithTimeout(url: string, init: RequestInit | undefined, timeoutMs: number): Promise<Response> {
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), timeoutMs);
	try {
		return await fetch(url, { ...(init ?? {}), signal: controller.signal });
	} finally {
		clearTimeout(timer);
	}
}

async function requestAnalysis(workspacePath: string, runExternalTools: boolean, workspaceTrusted: boolean): Promise<AnalysisResult> {
	const analyzerUrl = vscode.workspace.getConfiguration('terramind').get<string>('analyzerUrl', 'http://127.0.0.1:8000');
	const response = await fetchWithTimeout(`${analyzerUrl}/v1/analyze`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ workspace_path: workspacePath, run_external_tools: runExternalTools, workspace_trusted: workspaceTrusted })
	}, 120_000);
	if (!response.ok) {
		throw new Error(`Analyzer returned HTTP ${response.status}`);
	}
	return await response.json() as AnalysisResult;
}

interface GenerationJobStatus {
	readonly status: 'running' | 'completed' | 'failed';
	readonly progress: number;
	readonly phase: string;
	readonly detail: string | null;
	readonly result: GenerationResult | null;
}

/**
 * Queues generation on the analyzer and polls the Job API, reporting a real
 * percentage through a cancellable notification progress. Returns `undefined`
 * when the user cancels so callers can stop before presenting a draft.
 */
async function requestGenerationJob(
	description: string,
	resourceInventory: string,
	connectivity: string,
	constraints: string,
	model: string,
	workspacePath: string,
	runExternalTools: boolean,
	workspaceTrusted: boolean,
	onProgress?: (percent: number, phase: string) => void
): Promise<GenerationResult | undefined> {
	const analyzerUrl = vscode.workspace.getConfiguration('terramind').get<string>('analyzerUrl', 'http://127.0.0.1:8000');
	const engine = vscode.workspace.getConfiguration('terramind').get<string>('generationEngine', 'auto');
	return vscode.window.withProgress(
		{
			location: vscode.ProgressLocation.Notification,
			title: vscode.l10n.t('TerraMind: Generating a Terraform draft with the configured local model'),
			cancellable: true
		},
		async (progress, token) => {
			const startResponse = await fetch(`${analyzerUrl}/v1/generate/job`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					description,
					resource_inventory: resourceInventory,
					connectivity,
					constraints,
					model,
					engine,
					workspace_path: workspacePath,
					run_external_tools: runExternalTools,
					workspace_trusted: workspaceTrusted
				})
			});
			if (!startResponse.ok) {
				const error = await startResponse.json().catch(() => undefined) as { detail?: string } | undefined;
				throw new Error(error?.detail ?? `Analyzer returned HTTP ${startResponse.status}`);
			}
			const started = await startResponse.json() as { job_id?: string };
			if (!started.job_id) {
				throw new Error('The analyzer did not return a generation job id.');
			}
			const jobId = encodeURIComponent(started.job_id);
			let reported = 0;
			for (;;) {
				if (token.isCancellationRequested) {
					return undefined;
				}
				const statusResponse = await fetch(`${analyzerUrl}/v1/generate/job/${jobId}`);
				if (statusResponse.status === 404) {
					throw new Error('The analyzer no longer knows this generation job. Try again.');
				}
				if (!statusResponse.ok) {
					throw new Error(`Analyzer returned HTTP ${statusResponse.status}`);
				}
				const status = await statusResponse.json() as GenerationJobStatus;
				const percent = Math.max(0, Math.min(100, Math.round(status.progress ?? 0)));
				const phase = status.phase || 'working';
				progress.report({
					increment: Math.max(0, percent - reported),
					message: vscode.l10n.t('progress: {0}% · {1}', percent, phase)
				});
				reported = Math.max(reported, percent);
				if (onProgress) {
					onProgress(percent, phase);
				}
				if (status.status === 'completed') {
					return status.result ?? undefined;
				}
				if (status.status === 'failed') {
					throw new Error(status.detail ?? 'Terraform generation failed.');
				}
				await waitFor(500);
			}
		}
	);
}

function waitFor(milliseconds: number): Promise<void> {
	return new Promise(resolve => setTimeout(resolve, milliseconds));
}

async function requestRepair(
	terraform: string,
	findings: readonly string[],
	instructions: string,
	model: string,
	workspacePath: string,
	runExternalTools: boolean,
	workspaceTrusted: boolean
): Promise<GenerationResult> {
	const analyzerUrl = vscode.workspace.getConfiguration('terramind').get<string>('analyzerUrl', 'http://127.0.0.1:8000');
	const engine = vscode.workspace.getConfiguration('terramind').get<string>('generationEngine', 'auto');
	const response = await fetch(`${analyzerUrl}/v1/repair`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			terraform,
			findings,
			instructions,
			model,
			engine,
			workspace_path: workspacePath,
			run_external_tools: runExternalTools,
			workspace_trusted: workspaceTrusted
		})
	});
	if (!response.ok) {
		const error = await response.json().catch(() => undefined) as { detail?: string } | undefined;
		throw new Error(error?.detail ?? `Analyzer returned HTTP ${response.status}`);
	}
	return await response.json() as GenerationResult;
}

function getErrorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}
