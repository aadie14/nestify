import React, { useState } from 'react';
import axios from 'axios';
import { motion } from 'framer-motion';
import { Check, Copy, Sparkles, UploadCloud } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import StateMessage from '../components/ui/StateMessage';
import { useAnimation } from '../hooks/useAnimation';

const SAMPLE_GITHUB_INPUTS = [
  {
    label: 'Simple FastAPI API',
    url: 'https://github.com/tiangolo/fastapi',
    note: 'Backend Python app with clear runtime and dependency shape.',
  },
  {
    label: 'Next.js Fullstack App',
    url: 'https://github.com/vercel/next.js',
    note: 'Large modern web app; useful for architecture analysis stress tests.',
  },
  {
    label: 'Express Starter',
    url: 'https://github.com/expressjs/express',
    note: 'Node backend project for alternate platform recommendation paths.',
  },
];

const SAMPLE_LOCAL_ZIPS = [
  {
    name: 'sample_inputs/fastapi_todo_api.zip',
    note: 'Happy-path deployment sample for Python/FastAPI.',
  },
  {
    name: 'sample_inputs/broken_node_api.zip',
    note: 'Intentional runtime failure sample for remediation testing.',
  },
];

export default function UploadPage() {
  const navigate = useNavigate();
  const { fadeInUp } = useAnimation();

  const [file, setFile] = useState<File | null>(null);
  const [githubUrl, setGithubUrl] = useState('');
  const [sourceType, setSourceType] = useState<'file' | 'github'>('file');
  const [dragging, setDragging] = useState(false);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedSample, setCopiedSample] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<any>(null);
  const [provider, setProvider] = useState('auto');
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);

  React.useEffect(() => {
    let alive = true;
    const loadReadiness = async () => {
      try {
        const response = await axios.get('/api/v1/projects/deployment-readiness');
        if (!alive) return;
        setReadiness(response.data || null);
      } catch {
        if (!alive) return;
      }
    };
    loadReadiness();
    return () => {
      alive = false;
    };
  }, []);

  const copySampleUrl = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopiedSample(url);
      window.setTimeout(() => setCopiedSample((current) => (current === url ? null : current)), 1200);
    } catch {
      setCopiedSample(null);
    }
  };

  const deploy = async () => {
    if (loading) return;

    try {
      setLoading(true);
      setError(null);
      setActionFeedback('Received. Validating source and preparing autonomous analysis.');

      let res;
      if (sourceType === 'file') {
        if (!file) {
          setError('Please select a file to upload.');
          return;
        }

        const body = new FormData();
        body.append('file', file);
        body.append('agentic', 'true');
        body.append('provider', provider);
        res = await axios.post('/api/v1/projects/upload', body);
      } else {
        if (!githubUrl.trim()) {
          setError('Please enter a GitHub repository URL.');
          return;
        }

        res = await axios.post('/api/v1/projects/github', {
          github_url: githubUrl.trim(),
          provider,
        });
      }

      setProjectId(res.data.project_id);
      window.localStorage.setItem('nestify:lastProjectId', String(res.data.project_id));
      setActionFeedback('Project accepted. Opening live execution workspace...');
      navigate(`/analysis/${res.data.project_id}`);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      if (typeof detail === 'string' && detail.trim()) {
        setError(`${detail} Next: verify provider credentials in "Provider readiness" and retry.`);
      } else {
        setError('Upload failed before execution started. Next: confirm ZIP/GitHub access and try again.');
      }
      setActionFeedback(null);
    } finally {
      setLoading(false);
    }
  };

  const onDrop: React.DragEventHandler<HTMLLabelElement> = (event) => {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files?.[0] || null;
    setFile(dropped);
  };

  return (
    <div className="focus-shell" style={{ minHeight: 'calc(100vh - 120px)' }}>
      <motion.section className="page" initial={fadeInUp.initial} animate={fadeInUp.animate} transition={fadeInUp.transition}>
        <div className="pill minimal-pill">
          <Sparkles size={12} /> AI execution starts here
        </div>
        <h1 className="hero-title">Upload your app. Nestify handles the rest.</h1>
        <p className="muted" style={{ maxWidth: 760 }}>
          One action starts analysis, deployment planning, and autonomous execution. Technical detail is available when you need it.
        </p>
      </motion.section>

      <section className="focus-primary">
        <Card>
          <div style={{ display: 'inline-flex', gap: 8, marginBottom: 12 }}>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ opacity: sourceType === 'file' ? 1 : 0.75 }}
              onClick={() => {
                setSourceType('file');
                setError(null);
              }}
            >
              Upload File
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ opacity: sourceType === 'github' ? 1 : 0.75 }}
              onClick={() => {
                setSourceType('github');
                setError(null);
              }}
            >
              GitHub Link
            </button>
          </div>

          {sourceType === 'file' ? (
            <>
              <label
                className={`upload-zone ${dragging ? 'drag-active' : ''}`}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
              >
                <div
                  style={{
                    width: 72,
                    height: 72,
                    borderRadius: 999,
                    display: 'grid',
                    placeItems: 'center',
                    background: 'radial-gradient(circle at 40% 20%, rgba(139, 92, 246, 0.85), rgba(109, 40, 217, 0.4))',
                    boxShadow: 'var(--shadow-glow)',
                  }}
                >
                  <UploadCloud size={32} aria-label="Upload" />
                </div>
                <div>
                  <h3 style={{ margin: 0 }}>Drop your project bundle here</h3>
                  <p className="muted" style={{ marginTop: 8 }}>
                    ZIP repositories, app folders, or service source snapshots.
                  </p>
                </div>
                <input
                  type="file"
                  style={{ display: 'none' }}
                  onChange={(event) => setFile(event.target.files?.[0] || null)}
                  aria-label="Upload deployment file"
                />
                <Badge variant="intelligence">Max size 50MB • ZIP recommended</Badge>
              </label>

              {file ? (
                <div style={{ marginTop: 12, border: '1px solid #3f3f46', borderRadius: 10, padding: 10 }}>
                  <div style={{ fontWeight: 600 }}>{file.name}</div>
                  <div className="tiny">{(file.size / 1024 / 1024).toFixed(2)} MB</div>
                </div>
              ) : null}
            </>
          ) : (
            <div style={{ display: 'grid', gap: 10 }}>
              <h3 style={{ margin: 0 }}>Deploy from a GitHub repository</h3>
              <p className="muted" style={{ margin: 0 }}>
                Paste a repository URL like https://github.com/owner/repo and Nestify will analyze it directly.
              </p>
              <input
                className="input"
                placeholder="https://github.com/owner/repo"
                value={githubUrl}
                onChange={(event) => setGithubUrl(event.target.value)}
                aria-label="GitHub repository URL"
              />
            </div>
          )}

          <div style={{ marginTop: 14 }}>
            <div style={{ marginBottom: 10, display: 'grid', gap: 6 }}>
              <label className="tiny" htmlFor="provider-select">Deployment provider</label>
              <select
                id="provider-select"
                className="input"
                value={provider}
                onChange={(event) => setProvider(event.target.value)}
                aria-label="Preferred deployment provider"
              >
                <option value="auto">Auto-select best provider</option>
                <option value="vercel">Vercel</option>
                <option value="netlify">Netlify</option>
                <option value="railway">Railway</option>
                <option value="local">Local Preview</option>
              </select>
              {readiness?.messages?.length ? (
                <div className="tiny">{String(readiness.messages[0])}</div>
              ) : null}
            </div>
            <Button
              variant="primary"
              size="lg"
              loading={loading}
              onClick={deploy}
              disabled={sourceType === 'file' ? !file : !githubUrl.trim()}
            >
              {loading ? 'Starting AI execution...' : 'Start AI Execution'}
            </Button>
          </div>
          {loading ? (
            <StateMessage
              variant="loading"
              className="fade-in"
              title="Analyzing input and planning deployment"
              detail={actionFeedback || 'Building the execution plan and preparing agent collaboration.'}
            />
          ) : null}

          {actionFeedback && !loading ? (
            <StateMessage
              variant="success"
              className="fade-in"
              title="Action received"
              detail={actionFeedback}
            />
          ) : null}

          {error ? (
            <StateMessage
              variant="error"
              className="fade-in"
              title="Could not start execution"
              detail={error}
            />
          ) : null}

          {!loading && !error && sourceType === 'file' && !file ? (
            <StateMessage
              variant="empty"
              className="fade-in"
              title="Upload a project to begin"
              detail="Drop a ZIP file or switch to GitHub Link to continue."
            />
          ) : null}

          {!loading && !error && sourceType === 'github' && !githubUrl.trim() ? (
            <StateMessage
              variant="empty"
              className="fade-in"
              title="Upload a project to begin"
              detail="Paste a repository URL in the format https://github.com/owner/repo."
            />
          ) : null}

          {projectId ? <div className="tiny" style={{ marginTop: 8 }}>Project created: #{projectId}</div> : null}
        </Card>

        <details className="progressive-details" style={{ marginTop: 12 }}>
          <summary>How Nestify will execute this run</summary>
          <div className="progressive-details-body">
            <div className="tiny">1. Analyze architecture and dependencies</div>
            <div className="tiny">2. Evaluate deployment strategy and cost fit</div>
            <div className="tiny">3. Run autonomous deployment with transparent reasoning</div>
          </div>
        </details>

        <details className="progressive-details" style={{ marginTop: 12 }}>
          <summary>Provider readiness</summary>
          <div className="progressive-details-body">
            {readiness ? (
              <>
                <div className="tiny">Static: {readiness.static_ready ? 'Ready' : 'Needs VERCEL_TOKEN or NETLIFY_API_TOKEN'}</div>
                <div className="tiny">Backend: {readiness.backend_ready ? 'Ready' : 'Needs RAILWAY_API_KEY'}</div>
                <div className="tiny">GitHub import: {readiness.github_ready ? 'Ready' : 'Set GITHUB_TOKEN to avoid API limits'}</div>
                {Array.isArray(readiness.messages) && readiness.messages.length ? (
                  <ul className="tiny" style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 4 }}>
                    {readiness.messages.map((message: string, idx: number) => (
                      <li key={idx}>{message}</li>
                    ))}
                  </ul>
                ) : null}
              </>
            ) : (
              <div className="tiny">Checking provider readiness...</div>
            )}
          </div>
        </details>

        <details className="progressive-details" style={{ marginTop: 12 }}>
          <summary>Sample inputs</summary>
          <div className="progressive-details-body">
            <div className="sample-grid">
              {SAMPLE_GITHUB_INPUTS.map((sample) => {
                const copied = copiedSample === sample.url;
                return (
                  <article key={sample.url} className="sample-card">
                    <div style={{ display: 'grid', gap: 4 }}>
                      <strong>{sample.label}</strong>
                      <div className="tiny" style={{ lineHeight: 1.5 }}>{sample.note}</div>
                    </div>
                    <div className="sample-url">{sample.url}</div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => {
                          setSourceType('github');
                          setGithubUrl(sample.url);
                          setError(null);
                        }}
                      >
                        Use this URL
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        onClick={() => copySampleUrl(sample.url)}
                        aria-label={`Copy ${sample.label} URL`}
                      >
                        {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? 'Copied' : 'Copy'}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>

            <div style={{ borderTop: '1px solid #3f3f46', paddingTop: 10 }}>
              <h4 style={{ margin: '0 0 8px 0' }}>Local ZIP fixtures (already added to this repo)</h4>
              <div style={{ display: 'grid', gap: 8 }}>
                {SAMPLE_LOCAL_ZIPS.map((sample) => (
                  <div key={sample.name} className="sample-card" style={{ gridTemplateColumns: '1fr', gap: 6 }}>
                    <div className="sample-url">{sample.name}</div>
                    <div className="tiny">{sample.note}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </details>
      </section>
    </div>
  );
}
