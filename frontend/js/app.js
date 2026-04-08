/**
 * Nestify V1 — Frontend Application
 *
 * Handles: uploads, live progress, security report rendering,
 * deployment handoff status, preview, debug, and confetti.
 */

// ─── State ─────────────────────────────────────────────────────
let currentProjectId = null;
let ws = null;
let activeTab = 'zip';

const API_BASE = '';  // Same origin

// ─── Section Navigation ────────────────────────────────────────

function showSection(name) {
    // Hide hero
    document.getElementById('hero-section').classList.add('hidden');

    // Hide all sections
    ['upload', 'pipeline', 'results', 'debug'].forEach(s => {
        document.getElementById(`${s}-section`).classList.add('hidden');
    });

    // Show requested section
    const section = document.getElementById(`${name}-section`);
    if (section) {
        section.classList.remove('hidden');
        section.style.animation = 'none';
        section.offsetHeight; // trigger reflow
        section.style.animation = 'fadeInUp 0.5s ease-out';
    }
}

// ─── Tab Switching ─────────────────────────────────────────────

function switchTab(tab) {
    activeTab = tab;
    document.querySelectorAll('.upload-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.upload-panel').forEach(p => p.classList.remove('active'));

    document.querySelector(`.upload-tab[data-tab="${tab}"]`).classList.add('active');
    document.getElementById(`panel-${tab}`).classList.add('active');
}

function usePromptSample(prompt) {
    switchTab('nl');
    const input = document.getElementById('nl-description');
    if (!input) return;
    input.value = prompt;
    input.focus();
}

// ─── File Drop Zone ────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');

    if (!dropZone || !fileInput) return;

    dropZone.addEventListener('click', () => fileInput.click());

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragging');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragging');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragging');
        if (e.dataTransfer.files.length > 0) {
            fileInput.files = e.dataTransfer.files;
            const fileName = e.dataTransfer.files[0].name;
            dropZone.querySelector('.drop-text').textContent = `Selected: ${fileName}`;
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            dropZone.querySelector('.drop-text').textContent = `Selected: ${fileInput.files[0].name}`;
        }
    });
});

// ─── Submit Project ────────────────────────────────────────────

async function submitProject() {
    const submitBtn = document.getElementById('submit-btn');
    const btnText = submitBtn.querySelector('.btn-text');
    const btnLoading = submitBtn.querySelector('.btn-loading');

    btnText.classList.add('hidden');
    btnLoading.classList.remove('hidden');
    submitBtn.disabled = true;

    try {
        const formData = new FormData();
        const providerSelect = document.getElementById('provider-select');
        const requireApproval = document.getElementById('require-fix-approval');
        const agenticModeEnabled = document.getElementById('agentic-mode-enabled');
        formData.append('provider', providerSelect ? providerSelect.value : 'auto');
        formData.append('require_fix_approval', requireApproval && requireApproval.checked ? 'true' : 'false');
        formData.append('agentic', agenticModeEnabled && agenticModeEnabled.checked ? 'true' : 'false');

        if (activeTab === 'zip') {
            const fileInput = document.getElementById('file-input');
            if (!fileInput.files.length) {
                showToast('Please select a file to upload', 'error');
                return;
            }
            formData.append('file', fileInput.files[0]);
        } else if (activeTab === 'github') {
            const url = document.getElementById('github-url').value.trim();
            if (!url) {
                showToast('Please enter a GitHub URL', 'error');
                return;
            }
            formData.append('github_url', url);
        } else if (activeTab === 'text') {
            const text = document.getElementById('code-text').value.trim();
            if (!text) {
                showToast('Please paste some code', 'error');
                return;
            }
            formData.append('text', text);
        } else if (activeTab === 'nl') {
            const desc = document.getElementById('nl-description').value.trim();
            if (!desc) {
                showToast('Please describe your app', 'error');
                return;
            }
            formData.append('description', desc);
        }

        const response = await fetch(`${API_BASE}/api/upload`, {
            method: 'POST',
            body: formData,
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Upload failed');
        }

        currentProjectId = data.project_id;
        showToast(`Project "${data.name}" created. Security run starting...`, 'success');

        // Reset pipeline UI
        resetPipeline();

        // Connect WebSocket
        connectWebSocket(currentProjectId);

        // Show pipeline view
        showSection('pipeline');

        // Start polling as backup
        startPolling(currentProjectId);

    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        btnText.classList.remove('hidden');
        btnLoading.classList.add('hidden');
        submitBtn.disabled = false;
    }
}

// ─── WebSocket Connection ──────────────────────────────────────

function connectWebSocket(projectId) {
    if (ws) {
        ws.close();
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'subscribe', projectId }));
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleProgressUpdate(data);
    };

    ws.onerror = () => {
        console.log('[WS] Connection error, relying on polling');
    };

    ws.onclose = () => {
        console.log('[WS] Disconnected');
    };
}

// ─── Progress Handling ─────────────────────────────────────────

function handleProgressUpdate(data) {
    const statusText = document.getElementById('pipeline-status-text');
    if (statusText) {
        statusText.textContent = data.message || 'Processing...';
    }

    // Map V2 backend agent names to pipeline step element IDs
    const agentMap = {
        'SecurityAgent': 'agent-stack-analyzer',
        'FixAgent': 'agent-docker-architect',
        'DeploymentAgent': 'agent-deploy-agent',
        'Orchestrator': 'agent-complete',
    };

    const agentId = agentMap[data.agent];
    if (!agentId) return;

    const agentEl = document.getElementById(agentId);
    if (!agentEl) return;

    if (data.phase === 'error') {
        agentEl.dataset.status = 'error';
        agentEl.querySelector('.agent-status-badge').textContent = 'Error';
        agentEl.querySelector('.agent-desc').textContent = data.message;
        return;
    }

    if (data.phase === 'skipped') {
        agentEl.dataset.status = 'skipped';
        agentEl.querySelector('.agent-status-badge').textContent = 'Skipped';
        agentEl.querySelector('.agent-desc').textContent = data.message;
        return;
    }

    if (data.phase === 'complete') {
        // Mark pipeline complete
        agentEl.dataset.status = 'done';
        agentEl.querySelector('.agent-status-badge').textContent = 'Done';
        agentEl.querySelector('.agent-desc').textContent = data.message;

        // Show results
        if (data.data) {
            setTimeout(() => {
                renderResults(data.data);
                showSection('results');
            }, 1500);

            // Confetti if we have a live URL or passed review
            if (data.data.public_url || (data.data.meta_review && data.data.meta_review.verdict === 'PASS')) {
                launchConfetti();
            }
        }
        return;
    }

    if (data.phase === 'deployed') {
        // Deploy agent finished
        const deployEl = document.getElementById('agent-deploy-agent');
        if (deployEl) {
            deployEl.dataset.status = 'done';
            deployEl.querySelector('.agent-status-badge').textContent = 'Complete ✓';
            deployEl.querySelector('.agent-desc').textContent = data.message;
        }
        return;
    }

    // Mark previous agents as done, current as active
    const agentOrder = [
        'agent-stack-analyzer',
        'agent-docker-architect',
        'agent-safety-guard',
        'agent-meta-reviewer',
        'agent-deploy-agent',
    ];

    // For V2, also update intermediary steps when SecurityAgent rescans
    if (data.agent === 'SecurityAgent' && data.phase === 'rescanning') {
        const sg = document.getElementById('agent-safety-guard');
        if (sg) {
            sg.dataset.status = 'active';
            sg.querySelector('.agent-status-badge').textContent = 'Running...';
            sg.querySelector('.agent-desc').textContent = data.message;
        }
        return;
    }
    if (data.agent === 'SecurityAgent' && data.phase === 'complete' && data.message.includes('Rescan')) {
        ['agent-safety-guard', 'agent-meta-reviewer'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.dataset.status = 'done';
                el.querySelector('.agent-status-badge').textContent = 'Complete ✓';
                el.querySelector('.agent-desc').textContent = data.message;
            }
        });
        return;
    }

    const currentIndex = agentOrder.indexOf(agentId);
    agentOrder.forEach((id, i) => {
        const el = document.getElementById(id);
        if (!el) return;
        if (i < currentIndex) {
            el.dataset.status = 'done';
            el.querySelector('.agent-status-badge').textContent = 'Complete ✓';
        } else if (i === currentIndex) {
            el.dataset.status = 'active';
            el.querySelector('.agent-status-badge').textContent = 'Running...';
            el.querySelector('.agent-desc').textContent = data.message;
        }
    });
}

function resetPipeline() {
    const agents = [
        'agent-stack-analyzer', 'agent-docker-architect',
        'agent-safety-guard', 'agent-meta-reviewer',
        'agent-deploy-agent', 'agent-complete',
    ];
    agents.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.dataset.status = 'waiting';
            el.querySelector('.agent-status-badge').textContent = 'Waiting';
        }
    });
    document.getElementById('pipeline-status-text').textContent = 'Security run starting...';
}

// ─── Polling (Backup) ──────────────────────────────────────────

let pollInterval = null;

function startPolling(projectId) {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
        try {
            const resp = await fetch(`${API_BASE}/api/status/${projectId}`);
            const data = await resp.json();

            if (['completed', 'live', 'failed'].includes(data.project.status)) {
                clearInterval(pollInterval);
                pollInterval = null;

                // If we have results, render them
                if (data.project.security_report || data.project.fix_report) {
                    const results = {
                        status: data.project.status,
                        security_report: data.project.security_report,
                        security_score: data.project.security_score,
                        fix_report: data.project.fix_report,
                        agentic_insights: data.project.agentic_insights,
                        pipeline_state: data.project.pipeline_state,
                        public_url: data.project.public_url,
                        deployment: data.deployment,
                        logs: data.logs || [],
                    };
                    renderResults(results);

                    // Auto-switch to results if still on pipeline view
                    const pipelineSection = document.getElementById('pipeline-section');
                    if (!pipelineSection.classList.contains('hidden')) {
                        setTimeout(() => showSection('results'), 1000);
                    }
                }
            }

            // Process progress updates
            if (data.progress) {
                data.progress.forEach(p => handleProgressUpdate(p));
            }
        } catch (e) {
            console.error('Polling error:', e);
        }
    }, 2000);
}

// ─── Render Results ────────────────────────────────────────────

function renderResults(data) {
    const securityContent = document.getElementById('security-content');
    const metaReviewContent = document.getElementById('meta-review-content');
    const liveCard = document.getElementById('card-live-url');
    const liveLink = document.getElementById('live-url-link');
    const liveMeta = document.getElementById('live-url-meta');
    const livePreviewCard = document.getElementById('card-live-preview');
    const livePreviewFrame = document.getElementById('live-preview-frame');
    const livePreviewOpen = document.getElementById('live-preview-open');
    const dockerCard = document.getElementById('card-dockerfile');
    const composeCard = document.getElementById('card-compose');
    const agenticInsightsContent = document.getElementById('agentic-insights-content');

    // Hide Docker cards (V2 doesn't generate Dockerfiles)
    if (dockerCard) dockerCard.classList.add('hidden');
    if (composeCard) composeCard.classList.add('hidden');

    // Security report (V2 format: { critical: [...], high: [...], medium: [...], info: [...] })
    const securityReport = data.security_report
        ? (typeof data.security_report === 'string' ? JSON.parse(data.security_report) : data.security_report)
        : null;
    const score = data.security_score || 0;

    // Flatten all findings
    const allFindings = securityReport
        ? [...(securityReport.critical || []), ...(securityReport.high || []), ...(securityReport.medium || []), ...(securityReport.info || [])]
        : [];

    // Fix report (V2 format)
    const fixReport = data.fix_report
        ? (typeof data.fix_report === 'string' ? JSON.parse(data.fix_report) : data.fix_report)
        : null;
    const deploymentGate = fixReport?.deployment_gate || null;
    const agenticInsights = data.agentic_insights
        ? (typeof data.agentic_insights === 'string' ? JSON.parse(data.agentic_insights) : data.agentic_insights)
        : null;

    // Live URL
    if (data.public_url && liveCard && liveLink) {
        liveCard.classList.remove('hidden');
        liveLink.href = data.public_url;
        liveLink.textContent = data.public_url;
        if (liveMeta) {
            const dep = data.deployment;
            const provider = dep?.provider || 'provider';
            liveMeta.textContent = `Deployed to ${provider.charAt(0).toUpperCase() + provider.slice(1)}.`;
        }
        if (livePreviewCard && livePreviewFrame && livePreviewOpen) {
            livePreviewCard.classList.remove('hidden');
            livePreviewFrame.src = data.public_url;
            livePreviewOpen.href = data.public_url;
        }
    } else if (liveCard && liveLink && liveMeta) {
        liveCard.classList.remove('hidden');
        liveLink.removeAttribute('href');
        if (data.status === 'completed') {
            if (deploymentGate) {
                liveLink.textContent = deploymentGate.ready_to_deploy ? 'Ready to deploy' : 'Deployment requires review';
                liveMeta.textContent = deploymentGate.ready_to_deploy
                    ? 'Rescan passed. Click Deploy Now in Remediation Plan.'
                    : 'Rescan completed but deployment checklist has blockers.';
            } else {
                liveLink.textContent = 'Ready for manual deploy action';
                liveMeta.textContent = 'Scan finished. Use Deploy Now in Remediation Plan to continue deployment.';
            }
        } else if (data.status === 'failed') {
            liveLink.textContent = 'Pipeline failed';
            const errLog = (data.logs || []).reverse().find(l => l.level === 'error');
            liveMeta.textContent = errLog ? errLog.message : 'An error occurred during pipeline execution.';
        } else {
            liveLink.textContent = 'Deployment pending';
            liveMeta.textContent = 'Waiting for pipeline to complete...';
        }
    }

    // Stack summary — show score + scan metadata
    const stackContent = document.getElementById('stack-summary-content');
    if (stackContent) {
        const scoreColor = score >= 70 ? '#10b981' : score >= 40 ? '#f59e0b' : '#ef4444';
        const pipelineState = data.pipeline_state
            ? (typeof data.pipeline_state === 'string' ? JSON.parse(data.pipeline_state) : data.pipeline_state)
            : {};
        stackContent.innerHTML = `
            <div class="stack-grid">
                <div class="stack-item"><div class="stack-label">Security Score</div><div class="stack-value" style="color: ${scoreColor}; font-size: 1.4em; font-weight: 700;">${score}/100</div></div>
                <div class="stack-item"><div class="stack-label">Total Findings</div><div class="stack-value">${allFindings.length}</div></div>
                <div class="stack-item"><div class="stack-label">Critical</div><div class="stack-value" style="color: #ef4444;">${(securityReport?.critical || []).length}</div></div>
                <div class="stack-item"><div class="stack-label">High</div><div class="stack-value" style="color: #f97316;">${(securityReport?.high || []).length}</div></div>
                <div class="stack-item"><div class="stack-label">Medium</div><div class="stack-value" style="color: #f59e0b;">${(securityReport?.medium || []).length}</div></div>
                <div class="stack-item"><div class="stack-label">Info</div><div class="stack-value">${(securityReport?.info || []).length}</div></div>
                <div class="stack-item"><div class="stack-label">SecurityAgent</div><div class="stack-value">${pipelineState.security_agent || '—'}</div></div>
                <div class="stack-item"><div class="stack-label">FixAgent</div><div class="stack-value">${pipelineState.fix_agent || '—'}</div></div>
            </div>
        `;
    }

    // Hosting plan — show fix summary
    const hostingPlanContent = document.getElementById('hosting-plan-content');
    if (hostingPlanContent && fixReport) {
        const applied = fixReport.applied || [];
        const manual = fixReport.manual_review || [];
        const envVars = fixReport.env_vars_detected || [];
        hostingPlanContent.innerHTML = `
            <div class="stack-grid">
                <div class="stack-item"><div class="stack-label">Auto-fixes applied</div><div class="stack-value" style="color: #10b981; font-size: 1.2em;">${applied.length}</div></div>
                <div class="stack-item"><div class="stack-label">Flagged for review</div><div class="stack-value" style="color: #f59e0b; font-size: 1.2em;">${manual.length}</div></div>
                <div class="stack-item" style="grid-column: span 2"><div class="stack-label">Env vars detected</div><div class="stack-value">${envVars.length > 0 ? envVars.join(', ') : 'None'}</div></div>
            </div>
            ${applied.length > 0 ? '<h4 style="margin: 16px 0 8px; color: var(--text-primary);">✅ Applied fixes</h4>' + applied.map(f => `<div class="security-issue" style="border-left: 3px solid #10b981; padding: 8px 12px; margin: 4px 0; background: rgba(16,185,129,0.05); border-radius: 6px;"><strong>${f.fix_type}</strong> — ${f.note}<br/><small style="opacity:0.6;">${f.file}</small></div>`).join('') : ''}
            ${manual.length > 0 ? '<h4 style="margin: 16px 0 8px; color: var(--text-primary);">⚠️ Manual review required</h4>' + manual.map(f => `<div class="security-issue" style="border-left: 3px solid #f59e0b; padding: 8px 12px; margin: 4px 0; background: rgba(245,158,11,0.05); border-radius: 6px;"><strong>${f.fix_type}</strong> — ${f.note}<br/><small style="opacity:0.6;">${f.file}</small></div>`).join('') : ''}
        `;
    } else if (hostingPlanContent) {
        hostingPlanContent.innerHTML = '<p class="empty-state">No fixes required — code is clean.</p>';
    }

    // Security findings list
    if (securityContent && allFindings.length > 0) {
        const sevColors = { critical: '#ef4444', high: '#f97316', medium: '#f59e0b', info: '#64748b' };
        let html = '';
        allFindings.forEach(f => {
            const sev = f.severity || 'info';
            html += `
                <div class="security-issue" style="border-left: 3px solid ${sevColors[sev] || '#64748b'}; padding: 10px 14px; margin: 6px 0; background: rgba(255,255,255,0.02); border-radius: 6px;">
                    <span style="display: inline-block; background: ${sevColors[sev] || '#64748b'}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.75em; font-weight: 600; text-transform: uppercase; margin-right: 8px;">${sev}</span>
                    <strong>${f.title || f.type}</strong>
                    <p style="margin: 6px 0 2px; opacity: 0.8;">${f.description}</p>
                    ${f.file ? `<small style="opacity:0.5;">📄 ${f.file}${f.line ? ':' + f.line : ''}</small>` : ''}
                    ${f.recommendation ? `<p style="margin: 4px 0 0; color: #60a5fa;">💡 ${f.recommendation}</p>` : ''}
                </div>
            `;
        });
        securityContent.innerHTML = html;
    } else if (securityContent) {
        securityContent.innerHTML = '<p class="empty-state">No security issues detected. ✅</p>';
    }

    // Remediation Plan summary
    if (metaReviewContent) {
        const applied = fixReport?.applied || [];
        const manual = fixReport?.manual_review || [];
        const deployable = score >= 70;
        const verdictClass = deployable ? 'pass' : 'fail';
        const verdict = deployable ? 'READY' : 'REVIEW';
        const deploymentFailed = !!(data.deployment && data.deployment.status === 'failed');
        const waitingForApproval = !!(
            data.pipeline_state && (
                data.pipeline_state.fix_agent === 'awaiting_user_approval'
                || data.pipeline_state.deployment_agent === 'awaiting_user_approval'
            )
        );
        const hasFindings = allFindings.length > 0;
        const canOfferAutoFix = (hasFindings || deploymentFailed) && data.status !== 'live';

        const approvalActions = waitingForApproval ? `
            <div style="margin-top: 16px; display:flex; gap:10px; flex-wrap:wrap;">
                <button class="submit-btn" style="width:auto; padding:10px 14px;" onclick="chooseManualChanges()">I will apply changes myself</button>
                <button class="submit-btn" style="width:auto; padding:10px 14px;" onclick="autoFixAndDeploy()">Let Nestify fix for you</button>
            </div>
            <p class="input-hint" style="margin-top:8px;">Nestify will apply recommended fixes, rerun audit, then deploy.</p>
        ` : '';

        const autoFixQuickAction = (!waitingForApproval && canOfferAutoFix) ? `
            <div style="margin-top: 16px; display:flex; gap:10px; flex-wrap:wrap;">
                <button class="submit-btn" style="width:auto; padding:10px 14px;" onclick="autoFixAndDeploy()">Let Nestify fix everything and redeploy</button>
            </div>
            <p class="input-hint" style="margin-top:8px;">${deploymentFailed
                ? 'Deployment failed. Nestify will apply remediations, rerun the scan, and attempt deployment again.'
                : 'Applies safe fixes, reruns scan, and deploys updated code automatically.'
            }</p>
        ` : '';

        const gateChecklist = deploymentGate ? `
            <div class="stack-grid" style="margin-top: 16px;">
                <div class="stack-item"><div class="stack-label">Security Score</div><div class="stack-value">${deploymentGate.security_score}/100</div></div>
                <div class="stack-item"><div class="stack-label">Simulation</div><div class="stack-value">${deploymentGate.simulation_passed ? 'Passed' : 'Failed'}</div></div>
                <div class="stack-item"><div class="stack-label">High-Risk Dependencies</div><div class="stack-value">${deploymentGate.no_high_risk_dependencies ? 'None' : 'Detected'}</div></div>
                <div class="stack-item"><div class="stack-label">Deployment Safety</div><div class="stack-value">${deploymentGate.deployment_safe ? 'Safe' : 'Review required'}</div></div>
            </div>
            <div style="margin-top: 12px; border:1px solid rgba(16,185,129,0.3); background: rgba(16,185,129,0.06); border-radius: 10px; padding: 12px;">
                <div>✔ Security Score: ${deploymentGate.security_score}/100</div>
                <div>${deploymentGate.simulation_passed ? '✔' : '✖'} Simulation ${deploymentGate.simulation_passed ? 'Passed' : 'Failed'}</div>
                <div>${deploymentGate.no_high_risk_dependencies ? '✔' : '✖'} No high-risk dependencies</div>
                <div>${deploymentGate.deployment_safe ? '✔' : '✖'} Deployment ${deploymentGate.deployment_safe ? 'Safe' : 'Needs review'}</div>
            </div>
            <div style="margin-top: 12px; display:flex; gap:10px; flex-wrap:wrap;">
                <button class="submit-btn" style="width:auto; padding:10px 14px;" onclick="deployNowFromGate()" ${deploymentGate.ready_to_deploy ? '' : 'disabled'}>Deploy Now</button>
            </div>
        ` : '';

        const deployFallbackAction = (!deploymentGate && data.status === 'completed' && !data.public_url) ? `
            <div style="margin-top: 16px; border:1px solid rgba(96,165,250,0.35); background: rgba(59,130,246,0.08); border-radius: 10px; padding: 12px;">
                <div style="margin-bottom: 8px;">Scan and remediation finished. You can trigger deployment now.</div>
                <button class="submit-btn" style="width:auto; padding:10px 14px;" onclick="deployNowFromGate()">Deploy Now</button>
            </div>
        ` : '';

        metaReviewContent.innerHTML = `
            <div class="meta-verdict">
                <div class="verdict-badge ${verdictClass}">${verdict}</div>
                <div class="verdict-score">
                    <div class="score-number">${score}</div>
                    <div class="score-label">security score</div>
                </div>
                <div class="verdict-summary">
                    ${deployable
                ? 'Security score meets the deployment threshold. The project is ready for deployment.'
                : `Security score (${score}/100) is below the deployment threshold (70). Resolve the flagged issues to enable deployment.`
            }
                </div>
            </div>
            <div class="stack-grid" style="margin-top: 16px;">
                <div class="stack-item"><div class="stack-label">Auto-fixes applied</div><div class="stack-value">${applied.length}</div></div>
                <div class="stack-item"><div class="stack-label">Manual review items</div><div class="stack-value">${manual.length}</div></div>
                <div class="stack-item"><div class="stack-label">Deploy threshold</div><div class="stack-value">70/100</div></div>
                <div class="stack-item"><div class="stack-label">Status</div><div class="stack-value">${data.status || 'unknown'}</div></div>
            </div>
            ${gateChecklist}
            ${deployFallbackAction}
            ${approvalActions}
            ${autoFixQuickAction}
        `;
    }

    if (agenticInsightsContent) {
        if (!agenticInsights || Object.keys(agenticInsights).length === 0) {
            agenticInsightsContent.innerHTML = '<p class="empty-state">No agentic insights for this run. Enable agentic mode during upload.</p>';
        } else {
            const codeProfile = agenticInsights.code_profile || {};
            const secReasoning = agenticInsights.security_reasoning || {};
            const cost = agenticInsights.cost_optimization || {};
            const deployIntel = agenticInsights.deployment_intelligence || {};
            const selfHeal = agenticInsights.self_healing_report || {};
            const production = agenticInsights.production_insights || {};
            const proactive = Array.isArray(agenticInsights.proactive_actions) ? agenticInsights.proactive_actions : [];

            agenticInsightsContent.innerHTML = `
                <div class="stack-grid">
                    <div class="stack-item"><div class="stack-label">Code profile</div><div class="stack-value">${codeProfile.app_type || 'n/a'} / ${codeProfile.framework || 'n/a'}</div></div>
                    <div class="stack-item"><div class="stack-label">Runtime</div><div class="stack-value">${codeProfile.runtime || 'n/a'}</div></div>
                    <div class="stack-item"><div class="stack-label">Deploy complexity</div><div class="stack-value">${codeProfile.deployment_complexity_score ?? 'n/a'}</div></div>
                    <div class="stack-item"><div class="stack-label">Recommended platform</div><div class="stack-value">${deployIntel.chosen_platform || 'n/a'}</div></div>
                    <div class="stack-item"><div class="stack-label">Cost estimate</div><div class="stack-value">${deployIntel.estimated_monthly_cost_usd ? '$' + deployIntel.estimated_monthly_cost_usd + '/mo' : 'n/a'}</div></div>
                    <div class="stack-item"><div class="stack-label">Self-healing status</div><div class="stack-value">${selfHeal.status || 'n/a'}</div></div>
                </div>
                <h4 style="margin:16px 0 8px;">Security reasoning</h4>
                <p style="opacity:0.85;">${secReasoning.summary || 'No enriched security summary available.'}</p>
                <h4 style="margin:16px 0 8px;">Proactive actions</h4>
                ${proactive.length > 0
                    ? proactive.map(a => `<div class="security-issue" style="border-left:3px solid #45d0c5; padding:8px 12px; margin:4px 0; background:rgba(69,208,197,0.08); border-radius:6px;"><strong>${a.action || 'action'}</strong> — confidence ${a.confidence ?? 'n/a'}<br/><small style="opacity:0.7;">${a.rationale || ''}</small></div>`).join('')
                    : '<p class="empty-state">No proactive actions generated for this run.</p>'
                }
                ${production.metrics
                    ? `<h4 style="margin:16px 0 8px;">Production sampling</h4><div class="stack-grid"><div class="stack-item"><div class="stack-label">p95 latency</div><div class="stack-value">${production.metrics.p95_ms ?? 'n/a'} ms</div></div><div class="stack-item"><div class="stack-label">Error rate</div><div class="stack-value">${production.metrics.error_rate ?? 'n/a'}</div></div></div>`
                    : ''
                }
            `;
        }
    }

    void refreshIntelligencePanels(data);
}

function formatPercent(value) {
    const num = Number(value || 0);
    return `${(num * 100).toFixed(1)}%`;
}

async function refreshIntelligencePanels(resultData = null) {
    await Promise.all([
        refreshLearningStats(),
        refreshOptimizationInsights(resultData),
    ]);
}

async function refreshLearningStats() {
    const el = document.getElementById('learning-intelligence-content');
    if (!el) return;

    try {
        const resp = await fetch(`${API_BASE}/api/v1/learning/stats`);
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Unable to load learning stats');

        const topFixes = (data.top_fix_patterns || []).slice(0, 4);
        const topSignals = (data.top_failure_signals || []).slice(0, 4);
        const trend = (data.trend_last_14_days || []).slice(-7);

        el.innerHTML = `
            <div class="stack-grid">
                <div class="stack-item"><div class="stack-label">Total patterns</div><div class="stack-value">${data.total_patterns || 0}</div></div>
                <div class="stack-item"><div class="stack-label">30-day patterns</div><div class="stack-value">${data.patterns_last_30_days || 0}</div></div>
                <div class="stack-item"><div class="stack-label">Success rate</div><div class="stack-value">${formatPercent(data.success_rate)}</div></div>
                <div class="stack-item"><div class="stack-label">First-attempt success</div><div class="stack-value">${formatPercent(data.first_attempt_success_rate)}</div></div>
                <div class="stack-item"><div class="stack-label">Self-heal recovery</div><div class="stack-value">${formatPercent(data.self_heal_recovery_rate)}</div></div>
                <div class="stack-item"><div class="stack-label">Recorded proactive actions</div><div class="stack-value">${data.proactive_actions_recorded || 0}</div></div>
            </div>
            <h4 style="margin:16px 0 8px;">Top fix patterns</h4>
            ${topFixes.length
                ? topFixes.map(item => `<div class="security-issue" style="border-left: 3px solid #0ea5e9; padding: 8px 12px; margin: 4px 0; background: rgba(14,165,233,0.08); border-radius: 6px;"><strong>${item.action}</strong> — ${item.count}</div>`).join('')
                : '<p class="empty-state">No fix patterns recorded yet.</p>'
            }
            <h4 style="margin:16px 0 8px;">Top failure signals</h4>
            ${topSignals.length
                ? topSignals.map(item => `<div class="security-issue" style="border-left: 3px solid #f97316; padding: 8px 12px; margin: 4px 0; background: rgba(249,115,22,0.08); border-radius: 6px;"><strong>${item.signal}</strong> — ${item.count}</div>`).join('')
                : '<p class="empty-state">No failure signals identified yet.</p>'
            }
            <h4 style="margin:16px 0 8px;">Recent trend (last 7 points)</h4>
            ${trend.length
                ? `<p style="opacity:0.85;">${trend.map(item => `${item.date}: ${item.patterns}`).join(' | ')}</p>`
                : '<p class="empty-state">Trend data will appear as learning records accumulate.</p>'
            }
        `;
    } catch (error) {
        el.innerHTML = `<p class="empty-state">Unable to load learning intelligence: ${error.message}</p>`;
    }
}

async function refreshOptimizationInsights(resultData = null) {
    const el = document.getElementById('optimization-intelligence-content');
    if (!el) return;

    if (!currentProjectId) {
        el.innerHTML = '<p class="empty-state">No active project selected yet.</p>';
        return;
    }

    const probeFromResult = resultData && resultData.public_url ? `?probe_url=${encodeURIComponent(resultData.public_url)}` : '';

    try {
        const resp = await fetch(`${API_BASE}/api/v1/optimization/${currentProjectId}/analyze${probeFromResult}`);
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Unable to load optimization analysis');

        const analysis = data.analysis || {};
        const recommended = (analysis.recommended || {});
        const recommendedConfig = recommended.config || {};
        const benchmark = recommended.benchmark || {};
        const maybeSavings = data.potential_monthly_savings_usd;
        const applied = data.already_applied || {};

        el.innerHTML = `
            <div class="stack-grid">
                <div class="stack-item"><div class="stack-label">Provider</div><div class="stack-value">${data.provider || 'n/a'}</div></div>
                <div class="stack-item"><div class="stack-label">Method</div><div class="stack-value">${analysis.method || 'n/a'}</div></div>
                <div class="stack-item"><div class="stack-label">Recommended memory</div><div class="stack-value">${recommendedConfig.memory_mb || 'n/a'} MB</div></div>
                <div class="stack-item"><div class="stack-label">Recommended CPU</div><div class="stack-value">${recommendedConfig.cpu || 'n/a'}</div></div>
                <div class="stack-item"><div class="stack-label">Est. monthly cost</div><div class="stack-value">$${data.recommended_monthly_cost_usd || 0}</div></div>
                <div class="stack-item"><div class="stack-label">p95 latency</div><div class="stack-value">${benchmark.p95_ms || 'n/a'} ms</div></div>
                <div class="stack-item"><div class="stack-label">Success rate</div><div class="stack-value">${formatPercent(benchmark.success_rate)}</div></div>
                <div class="stack-item"><div class="stack-label">Potential savings</div><div class="stack-value">${maybeSavings === null || maybeSavings === undefined ? 'n/a' : '$' + maybeSavings}</div></div>
            </div>
            ${applied && Object.keys(applied).length > 0
                ? `<div style="margin-top:12px; border:1px solid rgba(16,185,129,0.35); background: rgba(16,185,129,0.08); border-radius: 10px; padding: 12px;"><strong>Applied configuration:</strong> ${applied.provider || 'n/a'} / ${applied.config?.memory_mb || 'n/a'}MB / CPU ${applied.config?.cpu || 'n/a'}<br/><small style="opacity:0.7;">Applied at ${applied.applied_at || 'unknown time'}</small></div>`
                : '<p class="input-hint" style="margin-top:10px;">No applied optimization config recorded yet.</p>'
            }
        `;
    } catch (error) {
        el.innerHTML = `<p class="empty-state">Unable to load optimization intelligence: ${error.message}</p>`;
    }
}

async function analyzeOptimization() {
    await refreshOptimizationInsights();
    showToast('Optimization analysis refreshed.', 'success');
}

async function applyOptimization() {
    if (!currentProjectId) {
        showToast('No active project selected.', 'error');
        return;
    }
    try {
        const resp = await fetch(`${API_BASE}/api/v1/optimization/${currentProjectId}/apply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note: 'Applied from frontend optimization panel' }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Unable to apply optimization');
        showToast('Optimization config applied to project intelligence.', 'success');
        await refreshOptimizationInsights();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function chooseManualChanges() {
    if (!currentProjectId) {
        showToast('No active project selected.', 'error');
        return;
    }
    try {
        const resp = await fetch(`${API_BASE}/api/fix/${currentProjectId}/defer`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Unable to switch to manual remediation mode.');
        showToast('Manual remediation mode enabled. Apply changes and redeploy when ready.', 'success');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function autoFixAndDeploy() {
    if (!currentProjectId) {
        showToast('No active project selected.', 'error');
        return;
    }
    try {
        showToast('Auto-fix approved. Running remediation and rerunning scan...', 'info');
        showSection('pipeline');
        const resp = await fetch(`${API_BASE}/api/fix/${currentProjectId}/auto-apply-deploy`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Auto-fix and deploy failed.');
        showToast('Rescan complete. Review checklist and click Deploy Now.', 'success');
        startPolling(currentProjectId);
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function deployNowFromGate() {
    if (!currentProjectId) {
        showToast('No active project selected.', 'error');
        return;
    }

    try {
        showToast('Deploying now...', 'info');
        showSection('pipeline');
        const resp = await fetch(`${API_BASE}/api/deploy/${currentProjectId}`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Deployment failed.');
        showToast('Deployment complete. Loading live URL...', 'success');
        startPolling(currentProjectId);
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// ─── Debug ─────────────────────────────────────────────────────

async function debugError() {
    const input = document.getElementById('debug-input');
    const errorText = input.value.trim();
    if (!errorText) {
        showToast('Please paste an error message', 'error');
        return;
    }

    const submitBtn = document.querySelector('#debug-section .submit-btn');
    const btnText = submitBtn.querySelector('.btn-text');
    const btnLoading = submitBtn.querySelector('.btn-loading');

    btnText.classList.add('hidden');
    btnLoading.classList.remove('hidden');
    submitBtn.disabled = true;

    try {
        const resp = await fetch(`${API_BASE}/api/debug`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ error_text: errorText }),
        });

        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Debug failed');

        const resultCard = document.getElementById('debug-result');
        resultCard.classList.remove('hidden');
        document.getElementById('debug-content').innerHTML = `
            <div class="debug-field"><div class="debug-label">Error Type</div><div class="debug-value">${data.error_type}</div></div>
            <div class="debug-field"><div class="debug-label">Root Cause</div><div class="debug-value">${data.root_cause}</div></div>
            <div class="debug-field"><div class="debug-label">Explanation</div><div class="debug-value">${data.explanation}</div></div>
            <div class="debug-field"><div class="debug-label">Fix</div><div class="debug-value" style="font-family: var(--font-mono); background: var(--glass); padding: 12px; border-radius: 8px;">${data.fix}</div></div>
            <div class="debug-field"><div class="debug-label">Learning Note</div><div class="debug-value">${data.learning_note}</div></div>
        `;
    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        btnText.classList.remove('hidden');
        btnLoading.classList.add('hidden');
        submitBtn.disabled = false;
    }
}

// ─── Copy Code ─────────────────────────────────────────────────

function copyCode(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return;

    navigator.clipboard.writeText(el.textContent).then(() => {
        showToast('Copied to clipboard! 📋', 'success');
    });
}

// ─── Toast Notifications ───────────────────────────────────────

function showToast(message, type = 'info') {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => toast.remove(), 4000);
}

// ─── Confetti 🎉 ───────────────────────────────────────────────

function launchConfetti() {
    const canvas = document.getElementById('confetti-canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    const particles = [];
    const colors = ['#7c3aed', '#3b82f6', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#ec4899'];

    for (let i = 0; i < 150; i++) {
        particles.push({
            x: Math.random() * canvas.width,
            y: Math.random() * canvas.height - canvas.height,
            w: Math.random() * 10 + 4,
            h: Math.random() * 6 + 2,
            color: colors[Math.floor(Math.random() * colors.length)],
            speed: Math.random() * 4 + 2,
            angle: Math.random() * Math.PI * 2,
            spin: (Math.random() - 0.5) * 0.2,
            drift: (Math.random() - 0.5) * 2,
        });
    }

    let frame = 0;
    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        particles.forEach(p => {
            p.y += p.speed;
            p.x += p.drift;
            p.angle += p.spin;

            ctx.save();
            ctx.translate(p.x, p.y);
            ctx.rotate(p.angle);
            ctx.fillStyle = p.color;
            ctx.globalAlpha = Math.max(0, 1 - p.y / canvas.height);
            ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
            ctx.restore();
        });

        frame++;
        if (frame < 180) {
            requestAnimationFrame(animate);
        } else {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
    }

    animate();
}
