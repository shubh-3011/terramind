/*---------------------------------------------------------------------------------------------
 *  Copyright (c) TerraMind contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import type { AnalysisFinding, AnalysisResult, CostEstimate, RatingDimension, Recommendation, ServiceRating } from './extension';

const REPORT_VIEW_TYPE = 'terramind.report';
const SEVERITY_ORDER: readonly AnalysisFinding['severity'][] = ['error', 'warning', 'information'];

let reportPanel: vscode.WebviewPanel | undefined;

/**
 * Opens (or focuses) the singleton TerraMind report panel and renders the supplied analysis result.
 * The report is static HTML with a strict CSP; analyzer-provided text is escaped and never executed.
 */
export function showReport(context: vscode.ExtensionContext, workspaceName: string, report: AnalysisResult | undefined): void {
	const title = vscode.l10n.t('TerraMind Report');
	if (reportPanel) {
		reportPanel.title = title;
		reportPanel.webview.html = getHtml(workspaceName, report);
		reportPanel.reveal();
		return;
	}
	const panel = vscode.window.createWebviewPanel(REPORT_VIEW_TYPE, title, vscode.ViewColumn.Active, {
		enableScripts: false,
		retainContextWhenHidden: true,
		localResourceRoots: []
	});
	panel.webview.html = getHtml(workspaceName, report);
	panel.onDidDispose(() => {
		if (reportPanel === panel) {
			reportPanel = undefined;
		}
	});
	reportPanel = panel;
	context.subscriptions.push(panel);
}

/** Disposes the report panel if it is open. Safe to call at any time. */
export function clearReport(): void {
	if (reportPanel) {
		reportPanel.dispose();
		reportPanel = undefined;
	}
}

function getHtml(workspaceName: string, report: AnalysisResult | undefined): string {
	const nonce = getNonce();
	const title = vscode.l10n.t('TerraMind Report');
	return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}'; img-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none';" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>${escapeHtml(title)}</title>
<style>
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
		max-width: 900px;
		line-height: 1.5;
	}
	a { color: var(--vscode-textLink-foreground, #0a66c2); }
	h1 { font-size: 1.4em; margin: 0 0 14px; }
	h2 {
		font-size: 1.15em;
		margin: 0 0 10px;
		padding-bottom: 6px;
		border-bottom: 1px solid var(--vscode-panel-border, rgba(128, 128, 128, 0.35));
	}
	h3 { font-size: 1em; margin: 14px 0 6px; display: flex; align-items: center; gap: 8px; }
	.section { margin-top: 26px; }
	.muted { color: var(--vscode-descriptionForeground, #6a6a6a); }
	.empty { color: var(--vscode-descriptionForeground, #6a6a6a); font-style: italic; margin: 0; }
	.workspace { margin: 0 0 8px; }
	.metrics { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 12px; }
	.metric { color: var(--vscode-descriptionForeground, #6a6a6a); }
	.metric.error strong { color: var(--vscode-errorForeground, #f85149); }
	.metric.warning strong { color: var(--vscode-editorWarning-foreground, #d29922); }
	.risk {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px;
		padding: 8px 12px;
		border: 1px solid var(--vscode-panel-border, rgba(128, 128, 128, 0.35));
		border-radius: 4px;
		background: var(--vscode-textBlockQuote-background, rgba(128, 128, 128, 0.1));
	}
	.risk-label { font-weight: 600; }
	.risk-value { font-size: 1.35em; font-weight: 700; }
	.chip {
		display: inline-block;
		padding: 1px 7px;
		border-radius: 10px;
		font-size: 0.78em;
		letter-spacing: 0.03em;
		text-transform: uppercase;
		border: 1px solid currentColor;
	}
	.chip-error { color: var(--vscode-errorForeground, #f85149); }
	.chip-warning { color: var(--vscode-editorWarning-foreground, #d29922); }
	.chip-information { color: var(--vscode-editorInfo-foreground, #3794ff); }
	.chip-experimental { color: var(--vscode-descriptionForeground, #6a6a6a); }
	.service {
		margin-bottom: 14px;
		padding: 10px 12px;
		border: 1px solid var(--vscode-panel-border, rgba(128, 128, 128, 0.35));
		border-radius: 4px;
	}
	.service-head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
	.service-name { font-weight: 600; }
	.dim { margin-bottom: 8px; }
	.dim-row { display: grid; grid-template-columns: 140px 1fr 72px; align-items: center; gap: 10px; }
	.dim-label { color: var(--vscode-descriptionForeground, #6a6a6a); }
	.bar {
		display: block;
		height: 8px;
		border-radius: 4px;
		background: var(--vscode-input-background, rgba(127, 127, 127, 0.25));
		overflow: hidden;
	}
	.bar-fill { display: block; height: 100%; background: var(--vscode-progressBar-background, #0e70c0); }
	.bar-good { background: var(--vscode-testing-iconPassed, #3fb950); }
	.bar-fair { background: var(--vscode-editorWarning-foreground, #d29922); }
	.bar-poor { background: var(--vscode-errorForeground, #f85149); }
	.score { text-align: right; font-variant-numeric: tabular-nums; }
	.not-rated { text-align: right; color: var(--vscode-descriptionForeground, #6a6a6a); font-style: italic; }
	.dim-details { margin: 4px 0 0 150px; color: var(--vscode-descriptionForeground, #6a6a6a); font-size: 0.92em; }
	.dim-summary { margin: 0 0 4px; }
	.detail-list { margin: 2px 0; }
	.detail-label { font-weight: 600; }
	.detail-list ul { margin: 2px 0 2px 18px; padding: 0; }
	.recommendations { list-style: none; margin: 0; padding: 0; }
	.rec {
		margin-bottom: 12px;
		padding: 10px 12px;
		border: 1px solid var(--vscode-panel-border, rgba(128, 128, 128, 0.35));
		border-radius: 4px;
	}
	.rec-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 6px; }
	.priority { font-weight: 700; }
	.rule {
		font-family: var(--vscode-editor-font-family, monospace);
		background: var(--vscode-textCodeBlock-background, rgba(127, 127, 127, 0.15));
		padding: 1px 5px;
		border-radius: 3px;
	}
	.count { color: var(--vscode-descriptionForeground, #6a6a6a); }
	.rec-title { margin: 0 0 4px; font-weight: 600; }
	.rec-text { margin: 0 0 4px; }
	.files, .location { color: var(--vscode-descriptionForeground, #6a6a6a); font-size: 0.9em; margin: 0; }
	.findings { list-style: none; margin: 0; padding: 0; }
	.finding { margin-bottom: 10px; padding: 8px 10px; border-left: 3px solid var(--vscode-panel-border, rgba(128, 128, 128, 0.35)); }
	.finding-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 4px; }
	.finding-message { margin: 0 0 4px; }
	.finding-recommendation { margin: 0; color: var(--vscode-descriptionForeground, #6a6a6a); }
	.cost-total { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; margin: 0 0 10px; }
	.cost-amount { font-size: 1.5em; font-weight: 700; font-variant-numeric: tabular-nums; }
	.cost-table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
	.cost-table th, .cost-table td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--vscode-panel-border, rgba(128, 128, 128, 0.3)); vertical-align: top; }
	.cost-table td.num, .cost-table th.num { text-align: right; }
	.cost-note { color: var(--vscode-descriptionForeground, #6a6a6a); font-size: 0.9em; margin: 6px 0 0; }
	.cost-assumption { color: var(--vscode-descriptionForeground, #6a6a6a); font-size: 0.88em; }
	.confidence-low { color: var(--vscode-editorWarning-foreground, #d29922); }
</style>
</head>
<body>
	<h1>${escapeHtml(title)}</h1>
	${renderHeader(workspaceName, report)}
	${renderCost(report)}
	${renderServiceScores(report)}
	${renderRecommendations(report)}
	${renderFindings(report)}
</body>
</html>`;
}

function formatUsd(value: number): string {
	return `$${(Number.isFinite(value) ? value : 0).toFixed(2)}`;
}

function formatQuantity(value: number): string {
	if (!Number.isFinite(value)) {
		return '0';
	}
	return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function renderCost(report: AnalysisResult | undefined): string {
	const cost: CostEstimate | null | undefined = report?.cost_estimate;
	if (!cost) {
		return '';
	}
	const items = cost.line_items.filter(item => item.monthly_usd > 0).slice(0, 20);
	const rows = items.map(item => `<tr>
		<td><span class="rule">${escapeHtml(item.resource_type)}</span>${item.assumption ? `<div class="cost-assumption">${escapeHtml(item.assumption)}</div>` : ''}</td>
		<td>${escapeHtml(item.billing_basis)}</td>
		<td class="num">${escapeHtml(formatQuantity(item.quantity))} ${escapeHtml(item.unit)}</td>
		<td class="num">${escapeHtml(formatUsd(item.unit_price_usd))}</td>
		<td class="num${item.confidence === 'low' ? ' confidence-low' : ''}">${escapeHtml(formatUsd(item.monthly_usd))}</td>
	</tr>`).join('');
	const table = items.length
		? `<table class="cost-table"><thead><tr><th>${escapeHtml(vscode.l10n.t('Resource'))}</th><th>${escapeHtml(vscode.l10n.t('Billing basis'))}</th><th class="num">${escapeHtml(vscode.l10n.t('Quantity'))}</th><th class="num">${escapeHtml(vscode.l10n.t('Unit price'))}</th><th class="num">${escapeHtml(vscode.l10n.t('Monthly'))}</th></tr></thead><tbody>${rows}</tbody></table>`
		: `<p class="empty">${escapeHtml(vscode.l10n.t('No directly billable resources were identified.'))}</p>`;
	const unpriced = cost.unpriced.length
		? `<p class="cost-note">${escapeHtml(vscode.l10n.t('{0} resource(s) are usage-based or unpriced and are excluded from the total:', cost.unpriced.length))}</p><ul class="detail-list">${cost.unpriced.slice(0, 12).map(entry => `<li><span class="rule">${escapeHtml(entry.resource_type)}</span> - ${escapeHtml(entry.reason)}</li>`).join('')}</ul>`
		: '';
	const notes = cost.notes.length
		? `<p class="cost-note">${cost.notes.map(note => escapeHtml(note)).join(' ')}</p>`
		: '';
	return `<section class="section">
		<h2>${escapeHtml(vscode.l10n.t('Estimated monthly cost'))} <span class="chip chip-experimental">${escapeHtml(vscode.l10n.t('estimate'))}</span></h2>
		<p class="cost-total"><span class="cost-amount">${escapeHtml(formatUsd(cost.total_monthly_usd))}</span><span class="muted">/ ${escapeHtml(vscode.l10n.t('month'))} · ${escapeHtml(cost.region)} · ${escapeHtml(vscode.l10n.t('{0} h/month', cost.assumed_hours_per_month))}</span></p>
		${table}
		${unpriced}
		${notes}
		<p class="cost-note">${escapeHtml(cost.disclaimer)}</p>
	</section>`;
}

function renderHeader(workspaceName: string, report: AnalysisResult | undefined): string {
	const parsed = report?.parsed_file_count ?? 0;
	const total = report?.terraform_file_count ?? 0;
	const findings = report?.findings ?? [];
	const errors = findings.filter(finding => finding.severity === 'error').length;
	const warnings = findings.filter(finding => finding.severity === 'warning').length;
	const status = report?.status ?? vscode.l10n.t('No analysis yet');
	return `<section class="header">
		<p class="workspace">${escapeHtml(vscode.l10n.t('Workspace'))}: <strong>${escapeHtml(workspaceName)}</strong></p>
		<div class="metrics">
			<span class="metric">${escapeHtml(vscode.l10n.t('Status'))}: <strong>${escapeHtml(status)}</strong></span>
			<span class="metric">${escapeHtml(vscode.l10n.t('Files parsed'))}: <strong>${parsed}</strong> / ${total}</span>
			<span class="metric error">${escapeHtml(vscode.l10n.t('Errors'))}: <strong>${errors}</strong></span>
			<span class="metric warning">${escapeHtml(vscode.l10n.t('Warnings'))}: <strong>${warnings}</strong></span>
		</div>
		${renderRisk(report)}
	</section>`;
}

function renderRisk(report: AnalysisResult | undefined): string {
	const label = escapeHtml(vscode.l10n.t('Experimental ML risk estimate'));
	const disclaimer = `<span class="chip chip-experimental">${escapeHtml(vscode.l10n.t('experimental / uncalibrated'))}</span>`;
	const prediction = report?.risk_prediction;
	if (prediction) {
		const percent = Math.round(prediction.probability * 100);
		return `<div class="risk">
			<span class="risk-label">${label}</span>
			<span class="risk-value">${percent}%</span>
			${disclaimer}
			<span class="muted">${escapeHtml(vscode.l10n.t('Label'))}: ${escapeHtml(prediction.label)} · ${escapeHtml(vscode.l10n.t('Model'))}: ${escapeHtml(prediction.model_version)} · ${escapeHtml(vscode.l10n.t('Training samples'))}: ${prediction.training_samples} · ${escapeHtml(prediction.calibrated ? vscode.l10n.t('calibrated') : vscode.l10n.t('uncalibrated'))}</span>
		</div>`;
	}
	const reason = report?.risk_prediction_reason?.trim();
	return `<div class="risk">
		<span class="risk-label">${label}</span>
		${disclaimer}
		<span class="muted">${escapeHtml(reason || vscode.l10n.t('Not available.'))}</span>
	</div>`;
}

function renderServiceScores(report: AnalysisResult | undefined): string {
	const ratings = report?.service_ratings ?? [];
	const body = ratings.length
		? ratings.map(renderServiceRating).join('')
		: `<p class="empty">${escapeHtml(vscode.l10n.t('No services were scored in the last analysis.'))}</p>`;
	return `<section class="section">
		<h2>${escapeHtml(vscode.l10n.t('Service scores'))}</h2>
		${body}
	</section>`;
}

function renderServiceRating(rating: ServiceRating): string {
	const dimensions: readonly (readonly [string, RatingDimension | undefined])[] = [
		[vscode.l10n.t('Security'), rating.dimensions?.security],
		[vscode.l10n.t('Reliability'), rating.dimensions?.reliability],
		[vscode.l10n.t('Maintainability'), rating.dimensions?.maintainability]
	];
	return `<div class="service">
		<div class="service-head">
			<span class="service-name">${escapeHtml(rating.service)}</span>
			<span class="muted">${escapeHtml(vscode.l10n.t('{0} resources', rating.resource_count))}</span>
		</div>
		${dimensions.map(([dimensionLabel, dimension]) => renderDimension(dimensionLabel, dimension)).join('')}
	</div>`;
}

function renderDimension(dimensionLabel: string, dimension: RatingDimension | undefined): string {
	if (!dimension || dimension.score === null || dimension.score === undefined) {
		return `<div class="dim">
			<div class="dim-row">
				<span class="dim-label">${escapeHtml(dimensionLabel)}</span>
				<span class="bar" aria-hidden="true"><span class="bar-fill" style="width: 0%"></span></span>
				<span class="not-rated">${escapeHtml(vscode.l10n.t('not rated'))}</span>
			</div>
		</div>`;
	}
	const score = clampScore(dimension.score);
	return `<div class="dim">
		<div class="dim-row">
			<span class="dim-label">${escapeHtml(dimensionLabel)}</span>
			<span class="bar" aria-hidden="true"><span class="bar-fill bar-${scoreBand(score)}" style="width: ${score}%"></span></span>
			<span class="score">${score}/100</span>
		</div>
		${renderDimensionDetails(dimension)}
	</div>`;
}

function renderDimensionDetails(dimension: RatingDimension): string {
	const parts: string[] = [];
	const summary = dimension.summary?.trim();
	if (summary) {
		parts.push(`<p class="dim-summary">${escapeHtml(summary)}</p>`);
	}
	const evidence = dimension.evidence ?? [];
	if (evidence.length) {
		parts.push(renderDetailList(vscode.l10n.t('Evidence'), evidence));
	}
	const evidenceFindingIds = dimension.evidence_finding_ids ?? [];
	if (evidenceFindingIds.length) {
		parts.push(renderDetailList(vscode.l10n.t('Evidence findings'), evidenceFindingIds));
	}
	const assumptions = dimension.assumptions ?? [];
	if (assumptions.length) {
		parts.push(renderDetailList(vscode.l10n.t('Assumptions'), assumptions));
	}
	const limitations = dimension.limitations ?? [];
	if (limitations.length) {
		parts.push(renderDetailList(vscode.l10n.t('Limitations'), limitations));
	}
	return parts.length ? `<div class="dim-details">${parts.join('')}</div>` : '';
}

function renderDetailList(label: string, items: readonly string[]): string {
	return `<div class="detail-list"><span class="detail-label">${escapeHtml(label)}</span><ul>${items.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div>`;
}

function renderRecommendations(report: AnalysisResult | undefined): string {
	const recommendations = [...(report?.recommendations ?? [])].sort((a, b) => a.priority - b.priority);
	const body = recommendations.length
		? `<ol class="recommendations">${recommendations.map(renderRecommendation).join('')}</ol>`
		: `<p class="empty">${escapeHtml(vscode.l10n.t('No recommendations were returned by the last analysis.'))}</p>`;
	return `<section class="section">
		<h2>${escapeHtml(vscode.l10n.t('Recommended improvements'))}</h2>
		${body}
	</section>`;
}

function renderRecommendation(recommendation: Recommendation): string {
	const files = recommendation.files ?? [];
	const text = recommendation.recommendation?.trim() || recommendation.message?.trim();
	return `<li class="rec">
		<div class="rec-head">
			<span class="priority">#${recommendation.priority}</span>
			<span class="chip chip-${severityClass(recommendation.severity)}">${escapeHtml(recommendation.severity)}</span>
			<code class="rule">${escapeHtml(recommendation.rule_id)}</code>
			<span class="count">${escapeHtml(vscode.l10n.t('{0}×', recommendation.count))}</span>
		</div>
		${recommendation.title ? `<p class="rec-title">${escapeHtml(recommendation.title)}</p>` : ''}
		${text ? `<p class="rec-text">${escapeHtml(text)}</p>` : ''}
		${files.length ? `<p class="files">${escapeHtml(vscode.l10n.t('Files'))}: ${files.map(file => escapeHtml(file)).join(', ')}</p>` : ''}
	</li>`;
}

function renderFindings(report: AnalysisResult | undefined): string {
	const findings = report?.findings ?? [];
	const heading = `<h2>${escapeHtml(vscode.l10n.t('Findings'))}</h2>`;
	if (!findings.length) {
		return `<section class="section">${heading}<p class="empty">${escapeHtml(vscode.l10n.t('No findings were reported by the last analysis.'))}</p></section>`;
	}
	const known = new Set<string>(SEVERITY_ORDER);
	const groups = SEVERITY_ORDER
		.map(severity => ({ severity, items: findings.filter(finding => finding.severity === severity).sort(compareFindings) }))
		.filter(group => group.items.length > 0);
	const other = findings.filter(finding => !known.has(finding.severity)).sort(compareFindings);
	if (other.length) {
		groups.push({ severity: 'information', items: other });
	}
	const body = groups.map(group => `<div class="finding-group">
		<h3><span class="chip chip-${severityClass(group.severity)}">${escapeHtml(group.severity)}</span><span class="muted">${escapeHtml(vscode.l10n.t('{0} finding(s)', group.items.length))}</span></h3>
		<ul class="findings">${group.items.map(renderFinding).join('')}</ul>
	</div>`).join('');
	return `<section class="section">${heading}${body}</section>`;
}

function renderFinding(finding: AnalysisFinding): string {
	const location = finding.line ? `${finding.file}:${finding.line}` : finding.file;
	return `<li class="finding">
		<div class="finding-head">
			<code class="rule">${escapeHtml(finding.rule_id)}</code>
			<span class="location">${escapeHtml(location)}</span>
		</div>
		<p class="finding-message">${escapeHtml(finding.message)}</p>
		${finding.recommendation ? `<p class="finding-recommendation">${escapeHtml(vscode.l10n.t('Recommendation'))}: ${escapeHtml(finding.recommendation)}</p>` : ''}
	</li>`;
}

function compareFindings(a: AnalysisFinding, b: AnalysisFinding): number {
	if (a.file !== b.file) {
		return a.file < b.file ? -1 : 1;
	}
	return (a.line ?? 0) - (b.line ?? 0);
}

function clampScore(score: number): number {
	if (!Number.isFinite(score)) {
		return 0;
	}
	return Math.max(0, Math.min(100, Math.round(score)));
}

function scoreBand(score: number): 'good' | 'fair' | 'poor' {
	if (score >= 80) {
		return 'good';
	}
	if (score >= 50) {
		return 'fair';
	}
	return 'poor';
}

function severityClass(severity: 'error' | 'warning' | 'information'): 'error' | 'warning' | 'information' {
	switch (severity) {
		case 'error':
			return 'error';
		case 'warning':
			return 'warning';
		default:
			return 'information';
	}
}

function getNonce(): string {
	// Web-safe: works in the browser workbench and in Node/Electron.
	const bytes = new Uint8Array(16);
	globalThis.crypto.getRandomValues(bytes);
	return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
}

function escapeHtml(value: string): string {
	return value
		.replaceAll('&', '&amp;')
		.replaceAll('<', '&lt;')
		.replaceAll('>', '&gt;')
		.replaceAll('"', '&quot;')
		.replaceAll("'", '&#39;');
}
