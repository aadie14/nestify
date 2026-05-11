import React from 'react';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import { Github, UploadCloud, FileCode2, Zap, CloudIcon } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Button from '../components/ui/Button';
import StateMessage from '../components/ui/StateMessage';
import GCPSetupWizard from '../components/GCPSetupWizard';

type SourceMode = 'code' | 'github' | 'zip';

export default function UploadPage() {
  const navigate = useNavigate();
  const [mode, setMode] = React.useState<SourceMode>('code');
  const [zipFile, setZipFile] = React.useState<File | null>(null);
  const [githubUrl, setGithubUrl] = React.useState('');
  const [codeText, setCodeText] = React.useState('');
  const [codeFilename, setCodeFilename] = React.useState('snippet.py');
  const [provider, setProvider] = React.useState('auto');
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [projectId, setProjectId] = React.useState<number | null>(null);
  const [showGCPWizard, setShowGCPWizard] = React.useState(false);

  const canSubmit =
    (mode === 'zip' && Boolean(zipFile)) ||
    (mode === 'github' && Boolean(githubUrl.trim())) ||
    (mode === 'code' && Boolean(codeText.trim()));

  const handleSubmit = async () => {
    if (!canSubmit || loading) return;
    try {
      setLoading(true);
      setError(null);

      const body = new FormData();
      body.append('agentic', 'true');
      body.append('provider', provider);

      if (mode === 'zip' && zipFile) {
        body.append('file', zipFile);
      }
      if (mode === 'github') {
        body.append('github_url', githubUrl.trim());
      }
      if (mode === 'code') {
        body.append('text', codeText);
        body.append('filename', codeFilename.trim() || 'snippet.py');
      }

      const response = await axios.post('/api/upload/', body);
      const nextProjectId = Number(response?.data?.project_id || 0);
      if (!nextProjectId) throw new Error('Project id missing from upload response');

      setProjectId(nextProjectId);
      window.localStorage.setItem('nestify:lastProjectId', String(nextProjectId));
      navigate(`/analysis/${nextProjectId}`);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' && detail ? detail : 'Could not start analysis. Verify source input and retry.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="neo-page">
      <motion.section
        className="neo-hero"
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
      >
        <div className="neo-kicker">Tab 1 · Input</div>
        <h1>Launch Autonomous DevSecOps Flow</h1>
      </motion.section>

      <section className="neo-panel glass">
        <div className="neo-mode-tabs" role="tablist" aria-label="Input source selector">
          <button type="button" className={`neo-tab ${mode === 'code' ? 'active' : ''}`} onClick={() => setMode('code')}>
            <FileCode2 size={14} />
            Code Paste Editor
          </button>
          <button type="button" className={`neo-tab ${mode === 'github' ? 'active' : ''}`} onClick={() => setMode('github')}>
            <Github size={14} />
            GitHub Repo
          </button>
          <button type="button" className={`neo-tab ${mode === 'zip' ? 'active' : ''}`} onClick={() => setMode('zip')}>
            <UploadCloud size={14} />
            ZIP Upload
          </button>
        </div>

        <div className="neo-input-body">
          {mode === 'code' ? (
            <div className="neo-stack">
              <div className="neo-row">
                <label htmlFor="raw-filename">Filename</label>
                <input
                  id="raw-filename"
                  className="neo-input"
                  value={codeFilename}
                  onChange={(event) => setCodeFilename(event.target.value)}
                  placeholder="app/main.py"
                />
              </div>
              <textarea
                className="neo-code-editor"
                value={codeText}
                onChange={(event) => setCodeText(event.target.value)}
                placeholder="Paste your source code here"
                aria-label="Raw pasted code"
              />
            </div>
          ) : null}

          {mode === 'github' ? (
            <div className="neo-stack">
              <label htmlFor="github-url">Repository URL</label>
              <input
                id="github-url"
                className="neo-input"
                value={githubUrl}
                onChange={(event) => setGithubUrl(event.target.value)}
                placeholder="https://github.com/owner/repo"
              />
            </div>
          ) : null}

          {mode === 'zip' ? (
            <label className="neo-drop-zone">
              <UploadCloud size={22} />
              <span>{zipFile ? zipFile.name : 'Drop ZIP or click to select'}</span>
              <input
                type="file"
                accept=".zip"
                onChange={(event) => setZipFile(event.target.files?.[0] || null)}
                style={{ display: 'none' }}
              />
            </label>
          ) : null}
        </div>

        <div className="neo-footer-actions">
          <select
            className="neo-input"
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
            aria-label="Preferred deployment provider"
          >
            <option value="auto">Auto provider</option>
            <option value="gcp">☁️ Google Cloud (Free)</option>
            <option value="vercel">Vercel</option>
            <option value="netlify">Netlify</option>
            <option value="railway">Railway</option>
          </select>
          <Button
            variant="primary"
            size="lg"
            loading={loading}
            onClick={handleSubmit}
            disabled={!canSubmit}
          >
            <Zap size={14} /> Analyze &amp; Prepare Deployment
          </Button>
        </div>

        {error ? <StateMessage variant="error" title="Input failed" detail={error} /> : null}
        {projectId ? <div className="tiny">Project #{projectId} created</div> : null}

        {provider === 'gcp' && (
          <div style={{ marginTop: 12 }}>
            <button
              type="button"
              onClick={() => setShowGCPWizard(true)}
              style={{
                background: 'linear-gradient(135deg, rgba(66,133,244,0.12), rgba(52,168,83,0.12))',
                border: '1px solid rgba(66,133,244,0.2)',
                borderRadius: 10,
                padding: '10px 18px',
                color: '#90caf9',
                fontSize: '0.82rem',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                fontWeight: 600,
              }}
            >
              <CloudIcon size={14} /> Set Up Google Cloud (First Time)
            </button>
          </div>
        )}
      </section>

      <AnimatePresence>
        {showGCPWizard && (
          <GCPSetupWizard
            onClose={() => setShowGCPWizard(false)}
            onConfigured={() => {}}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
