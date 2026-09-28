/*---------------------------------------------------------------------------------------------
 *  Copyright (c) TerraMind contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';

interface AnalysisResult {
	readonly terraform_file_count: number;
	readonly status: string;
}

class TerraMindDashboardProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
	private readonly _onDidChangeTreeData = new vscode.EventEmitter<void>();
	readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

	private analyzerStatus = 'Analyzer Not Checked';
	private workspaceStatus = 'No Analysis Run';

	refresh(analyzerStatus: string, workspaceStatus: string): void {
		this.analyzerStatus = analyzerStatus;
		this.workspaceStatus = workspaceStatus;
		this._onDidChangeTreeData.fire();
	}

	getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
		return element;
	}

	getChildren(): vscode.TreeItem[] {
		return [
			this.createItem('TerraMind Analyzer', this.analyzerStatus, 'server'),
			this.createItem('Terraform Workspace', this.workspaceStatus, 'file-code'),
			this.createItem('Security Rating', 'Available After Analysis', 'shield'),
			this.createItem('Reliability Rating', 'Available After Analysis', 'pulse'),
			this.createItem('Scalability Rating', 'Available After Analysis', 'graph')
		];
	}

	private createItem(label: string, description: string, icon: string): vscode.TreeItem {
		const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
		item.description = description;
		item.iconPath = new vscode.ThemeIcon(icon);
		return item;
	}
}

export function activate(context: vscode.ExtensionContext): void {
	const output = vscode.window.createOutputChannel('TerraMind');
	const dashboard = new TerraMindDashboardProvider();
	context.subscriptions.push(output, vscode.window.registerTreeDataProvider('terramind.dashboard', dashboard));

	context.subscriptions.push(vscode.commands.registerCommand('terramind.openDashboard', async () => {
		await vscode.commands.executeCommand('workbench.view.extension.terramind');
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
				const result = await requestAnalysis(workspaceFolder.uri.fsPath);
				const workspaceStatus = result.terraform_file_count > 0
					? vscode.l10n.t('{0} Terraform Files Found', result.terraform_file_count)
					: vscode.l10n.t('No Terraform Files Found');
				dashboard.refresh(vscode.l10n.t('Connected'), workspaceStatus);
				output.appendLine(`Analysis service returned status=${result.status}, terraform_file_count=${result.terraform_file_count}`);
				await vscode.window.showInformationMessage(vscode.l10n.t('TerraMind found {0} Terraform file(s). Analyzer integration is ready for the next validation stage.', result.terraform_file_count));
			} catch (error) {
				dashboard.refresh(vscode.l10n.t('Unavailable'), vscode.l10n.t('Analysis Not Run'));
				output.appendLine(`Analyzer request failed: ${getErrorMessage(error)}`);
				output.show(true);
				await vscode.window.showErrorMessage(vscode.l10n.t('TerraMind could not reach the local analyzer. Start the analyzer service and try again.'));
			}
		});
	}));

	context.subscriptions.push(vscode.commands.registerCommand('terramind.generateInfrastructure', async () => {
		const requirement = await vscode.window.showInputBox({
			prompt: vscode.l10n.t('Describe the AWS Terraform infrastructure you need.'),
			placeHolder: vscode.l10n.t('Example: 2 private application servers in one VPC with an S3 bucket')
		});
		if (!requirement) {
			return;
		}

		const constraints = await vscode.window.showInputBox({
			prompt: vscode.l10n.t('Add region, connectivity, security, cost, or availability constraints.'),
			placeHolder: vscode.l10n.t('Example: ap-south-1, no public SSH, target 99.9% availability')
		});
		output.appendLine(`Generation request captured. Requirement: ${requirement}`);
		output.appendLine(`Constraints: ${constraints ?? ''}`);
		output.show(true);
		await vscode.window.showInformationMessage(vscode.l10n.t('TerraMind captured your infrastructure request. Local LLM generation will be enabled after the analyzer pipeline is complete.'));
	}));
}

async function requestAnalysis(workspacePath: string): Promise<AnalysisResult> {
	const analyzerUrl = vscode.workspace.getConfiguration('terramind').get<string>('analyzerUrl', 'http://127.0.0.1:8000');
	const response = await fetch(`${analyzerUrl}/v1/analyze`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ workspace_path: workspacePath })
	});
	if (!response.ok) {
		throw new Error(`Analyzer returned HTTP ${response.status}`);
	}
	return await response.json() as AnalysisResult;
}

function getErrorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}
