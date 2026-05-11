import React from 'react';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle2, XCircle, Loader2, ChevronRight, ExternalLink, Copy, CloudIcon, Shield, Zap } from 'lucide-react';
import './GCPSetupWizard.css';

interface SetupStep {
  step: number;
  title: string;
  description: string;
  link: string | null;
  cli_alternative: string | null;
  estimated_time: string;
}

interface ValidationResult {
  ok: boolean;
  project_id?: string;
  error?: string;
  checks?: Record<string, any>;
}

interface GCPSetupWizardProps {
  onClose: () => void;
  onConfigured?: () => void;
}

export default function GCPSetupWizard({ onClose, onConfigured }: GCPSetupWizardProps) {
  const [steps, setSteps] = React.useState<SetupStep[]>([]);
  const [freeTier, setFreeTier] = React.useState<Record<string, any>>({});
  const [currentStep, setCurrentStep] = React.useState(0);
  const [projectId, setProjectId] = React.useState('');
  const [saJson, setSaJson] = React.useState('');
  const [validating, setValidating] = React.useState(false);
  const [validation, setValidation] = React.useState<ValidationResult | null>(null);
  const [enablingApis, setEnablingApis] = React.useState(false);
  const [copied, setCopied] = React.useState('');
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    axios.get('/api/v1/gcp/setup-guide').then((res) => {
      setSteps(res.data.steps || []);
      setFreeTier(res.data.free_tier_details || {});
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(''), 2000);
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const content = ev.target?.result as string;
      setSaJson(content);
      try {
        const parsed = JSON.parse(content);
        if (parsed.project_id) setProjectId(parsed.project_id);
      } catch { /* not valid json yet */ }
    };
    reader.readAsText(file);
  };

  const handleValidate = async () => {
    setValidating(true);
    setValidation(null);
    try {
      const res = await axios.post('/api/v1/gcp/configure', {
        project_id: projectId,
        service_account_json: saJson || null,
      });
      setValidation(res.data.validation);
      if (res.data.validation?.ok) onConfigured?.();
    } catch (err: any) {
      setValidation({ ok: false, error: err?.response?.data?.detail || 'Validation failed' });
    } finally {
      setValidating(false);
    }
  };

  const handleEnableApis = async () => {
    setEnablingApis(true);
    try {
      await axios.post('/api/v1/gcp/enable-apis', {
        project_id: projectId,
        service_account_json: saJson || null,
      });
      handleValidate();
    } catch { /* ignore */ }
    setEnablingApis(false);
  };

  if (loading) {
    return (
      <div className="gcp-wizard-overlay" onClick={onClose}>
        <div className="gcp-wizard" onClick={(e) => e.stopPropagation()}>
          <div className="gcp-wizard-loading"><Loader2 className="spin" size={28} /> Loading setup guide...</div>
        </div>
      </div>
    );
  }

  const isCredentialStep = currentStep === 4;
  const isValidationStep = currentStep === 5;
  const step = steps[currentStep];

  return (
    <div className="gcp-wizard-overlay" onClick={onClose}>
      <motion.div
        className="gcp-wizard"
        onClick={(e) => e.stopPropagation()}
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95 }}
        transition={{ duration: 0.25 }}
      >
        {/* Header */}
        <div className="gcp-wizard-header">
          <div className="gcp-wizard-header-icon">
            <CloudIcon size={24} />
          </div>
          <div>
            <h2>Deploy to Google Cloud — Free</h2>
            <p className="gcp-subtitle">2M requests/month · Scale-to-zero · $0.00/month</p>
          </div>
          <button className="gcp-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {/* Free Tier Banner */}
        {currentStep === 0 && (
          <div className="gcp-free-banner">
            <div className="gcp-free-stat"><Shield size={16} /> <strong>2,000,000</strong> requests/mo</div>
            <div className="gcp-free-stat"><Zap size={16} /> <strong>180,000</strong> vCPU-sec/mo</div>
            <div className="gcp-free-stat"><CloudIcon size={16} /> <strong>Scale to Zero</strong> = $0 idle</div>
          </div>
        )}

        {/* Step Indicators */}
        <div className="gcp-steps-bar">
          {steps.map((s, i) => (
            <button
              key={s.step}
              className={`gcp-step-dot ${i === currentStep ? 'active' : ''} ${i < currentStep ? 'done' : ''}`}
              onClick={() => setCurrentStep(i)}
              aria-label={`Step ${s.step}`}
            >
              {i < currentStep ? <CheckCircle2 size={16} /> : <span>{s.step}</span>}
            </button>
          ))}
        </div>

        {/* Step Content */}
        <AnimatePresence mode="wait">
          {step && (
            <motion.div
              key={currentStep}
              className="gcp-step-content"
              initial={{ opacity: 0, x: 30 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -30 }}
              transition={{ duration: 0.2 }}
            >
              <h3>{step.title}</h3>
              <p>{step.description}</p>
              <div className="gcp-time-badge">⏱ {step.estimated_time}</div>

              {step.link && (
                <a href={step.link} target="_blank" rel="noopener noreferrer" className="gcp-link-btn">
                  <ExternalLink size={14} /> Open in Google Cloud Console
                </a>
              )}

              {step.cli_alternative && (
                <div className="gcp-cli-block">
                  <div className="gcp-cli-header">
                    <span>CLI Alternative</span>
                    <button
                      onClick={() => copyToClipboard(step.cli_alternative!, `cli-${currentStep}`)}
                      className="gcp-copy-btn"
                    >
                      <Copy size={12} /> {copied === `cli-${currentStep}` ? 'Copied!' : 'Copy'}
                    </button>
                  </div>
                  <pre>{step.cli_alternative}</pre>
                </div>
              )}

              {/* Step 5: Credential Upload */}
              {isCredentialStep && (
                <div className="gcp-credential-zone">
                  <label className="gcp-drop-zone">
                    <CloudIcon size={20} />
                    <span>{saJson ? '✅ Key file loaded' : 'Drop JSON key file here or click to upload'}</span>
                    <input type="file" accept=".json" onChange={handleFileUpload} style={{ display: 'none' }} />
                  </label>
                  <div className="gcp-or">— or paste JSON below —</div>
                  <textarea
                    className="gcp-json-input"
                    value={saJson}
                    onChange={(e) => setSaJson(e.target.value)}
                    placeholder='{"type": "service_account", "project_id": "...", ...}'
                    rows={4}
                  />
                  <input
                    className="gcp-project-input"
                    value={projectId}
                    onChange={(e) => setProjectId(e.target.value)}
                    placeholder="GCP Project ID (e.g. my-project-123)"
                  />
                </div>
              )}

              {/* Step 6: Validation */}
              {isValidationStep && (
                <div className="gcp-validation-zone">
                  <button
                    className="gcp-validate-btn"
                    onClick={handleValidate}
                    disabled={validating || (!projectId && !saJson)}
                  >
                    {validating ? <><Loader2 className="spin" size={14} /> Validating...</> : 'Validate Credentials'}
                  </button>

                  {validation && (
                    <div className={`gcp-validation-result ${validation.ok ? 'success' : 'error'}`}>
                      {validation.ok ? (
                        <>
                          <CheckCircle2 size={20} />
                          <div>
                            <strong>All checks passed!</strong>
                            <p>Your GCP project <code>{validation.project_id}</code> is ready for free deployments.</p>
                          </div>
                        </>
                      ) : (
                        <>
                          <XCircle size={20} />
                          <div>
                            <strong>Validation failed</strong>
                            <p>{validation.error}</p>
                            {validation.checks?.apis && Object.entries(validation.checks.apis).some(([, v]) => v !== 'enabled') && (
                              <button className="gcp-enable-apis-btn" onClick={handleEnableApis} disabled={enablingApis}>
                                {enablingApis ? 'Enabling...' : 'Auto-enable required APIs'}
                              </button>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                  )}

                  {validation?.checks && (
                    <div className="gcp-checks-grid">
                      {Object.entries(validation.checks).map(([key, val]) => {
                        if (key === 'apis' && typeof val === 'object') {
                          return Object.entries(val as Record<string, string>).map(([api, status]) => (
                            <div key={api} className={`gcp-check ${status === 'enabled' ? 'pass' : 'fail'}`}>
                              {status === 'enabled' ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                              {api.replace('.googleapis.com', '')}
                            </div>
                          ));
                        }
                        const ok = val === 'ok' || val === 'enabled';
                        return (
                          <div key={key} className={`gcp-check ${ok ? 'pass' : 'fail'}`}>
                            {ok ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                            {key.replace(/_/g, ' ')}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Navigation */}
        <div className="gcp-wizard-nav">
          <button
            className="gcp-nav-btn secondary"
            onClick={() => setCurrentStep(Math.max(0, currentStep - 1))}
            disabled={currentStep === 0}
          >
            Back
          </button>
          <div className="gcp-step-label">Step {currentStep + 1} of {steps.length}</div>
          {currentStep < steps.length - 1 ? (
            <button className="gcp-nav-btn primary" onClick={() => setCurrentStep(currentStep + 1)}>
              Next <ChevronRight size={14} />
            </button>
          ) : (
            <button
              className="gcp-nav-btn primary"
              onClick={onClose}
              disabled={!validation?.ok}
            >
              Done
            </button>
          )}
        </div>
      </motion.div>
    </div>
  );
}
