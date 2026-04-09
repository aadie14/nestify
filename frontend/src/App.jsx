import React, { Suspense, lazy, useEffect, useMemo, useState } from 'react';
import { BrowserRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import axios from 'axios';
import { Check } from 'lucide-react';
import StateMessage from './components/ui/StateMessage';

const UploadPage = lazy(() => import('./pages/Upload'));
const AnalysisPage = lazy(() => import('./pages/Analysis'));
const DashboardPage = lazy(() => import('./pages/Dashboard'));
const DeploymentPage = lazy(() => import('./pages/Deployment'));

function AppFrame() {
  const location = useLocation();
  const navigate = useNavigate();
  const [lastProjectId, setLastProjectId] = useState(() => Number(window.localStorage.getItem('nestify:lastProjectId') || 0));
  const [journey, setJourney] = useState({
    hasProject: false,
    analysisComplete: false,
    deployComplete: false,
    monitorReady: false,
  });

  useEffect(() => {
    if (!lastProjectId || lastProjectId <= 0) {
      setJourney({ hasProject: false, analysisComplete: false, deployComplete: false, monitorReady: false });
      return;
    }

    let alive = true;
    const required = ['code_analysis', 'execution_test', 'agent_debate', 'security_audit', 'auto_fixes', 'cost_analysis'];
    const poll = async () => {
      try {
        const [statusRes, deployRes] = await Promise.all([
          axios.get(`/api/v1/projects/${lastProjectId}/status`),
          axios.get(`/api/v1/projects/${lastProjectId}/deployment`),
        ]);
        if (!alive) return;

        const statusData = statusRes.data || {};
        const status = String(statusData.status || '').toLowerCase();
        const pipeline = statusData.pipeline_state || {};
        const analysisComplete =
          status === 'completed' ||
          status === 'live' ||
          status === 'failed' ||
          required.every((step) => {
            const value = String(pipeline[step] || '').toLowerCase();
            return ['done', 'complete', 'completed', 'success', 'skipped'].includes(value);
          });

        const deployData = deployRes.data || {};
        const deployComplete = Boolean(deployData.deployment_url) || status === 'live' || status === 'completed';
        const monitorReady = deployComplete;

        setJourney({ hasProject: true, analysisComplete, deployComplete, monitorReady });
      } catch {
        if (!alive) return;
        setJourney({ hasProject: true, analysisComplete: false, deployComplete: false, monitorReady: false });
      }
    };

    poll();
    const timer = window.setInterval(poll, 3000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [lastProjectId]);

  useEffect(() => {
    const match = location.pathname.match(/\/(analysis|deployment|dashboard)\/(\d+)/);
    if (!match) return;
    const nextId = Number(match[2]);
    if (!Number.isFinite(nextId) || nextId <= 0) return;
    setLastProjectId(nextId);
    window.localStorage.setItem('nestify:lastProjectId', String(nextId));
  }, [location.pathname]);

  const navTargets = useMemo(() => {
    const suffix = lastProjectId > 0 ? String(lastProjectId) : null;
    return {
      upload: '/',
      analysis: suffix ? `/analysis/${suffix}` : '/',
      deployment: suffix ? `/deployment/${suffix}` : '/',
      dashboard: suffix ? `/dashboard/${suffix}` : '/',
    };
  }, [lastProjectId]);

  const navTabs = useMemo(() => {
    const upload = { key: 'upload', label: 'Input', path: navTargets.upload, enabled: true, complete: journey.hasProject };
    const analyse = {
      key: 'analyse',
      label: 'Analysis',
      path: navTargets.analysis,
      enabled: journey.hasProject,
      complete: journey.analysisComplete,
    };
    const deploy = {
      key: 'deploy',
      label: 'Deploy',
      path: navTargets.deployment,
      enabled: journey.analysisComplete,
      complete: journey.deployComplete,
    };
    const monitor = {
      key: 'monitor',
      label: 'Monitor',
      path: navTargets.dashboard,
      enabled: journey.deployComplete,
      complete: journey.monitorReady,
    };
    return [upload, analyse, deploy, monitor];
  }, [journey, navTargets]);

  const activeTabLabel = useMemo(() => {
    const active = navTabs.find((tab) => location.pathname === tab.path || location.pathname.startsWith(`${tab.path}/`));
    return active?.label || 'Input';
  }, [location.pathname, navTabs]);

  useEffect(() => {
    const path = location.pathname;
    if (!journey.hasProject && path !== '/') {
      navigate('/', { replace: true });
      return;
    }

    if (path.startsWith('/deployment/') && !journey.analysisComplete) {
      navigate(navTargets.analysis, { replace: true });
      return;
    }

    if (path.startsWith('/dashboard/')) {
      if (!journey.analysisComplete) {
        navigate(navTargets.analysis, { replace: true });
        return;
      }
      if (!journey.deployComplete) {
        navigate(navTargets.deployment, { replace: true });
      }
    }
  }, [journey, location.pathname, navigate, navTargets]);

  return (
    <div className="app-shell">
      <header className="app-nav minimal-nav">
        <div className="brand-mark minimal-brand">
          <span className="brand-orb" />
          <div>
            <div style={{ fontWeight: 700, letterSpacing: '-0.01em' }}>Nestify</div>
            <div className="brand-title">AI-Native Execution Interface</div>
          </div>
        </div>

        <div className="nav-meta">
          <div className="pill minimal-pill">
            {lastProjectId > 0 ? `Project #${lastProjectId}` : 'No project selected'}
          </div>
          <div className="tiny" style={{ whiteSpace: 'nowrap' }}>Focus: {activeTabLabel}</div>
          <nav className="nav-links minimal-links" aria-label="Primary navigation">
            {navTabs.map((tab) => {
              const active = location.pathname === tab.path || location.pathname.startsWith(`${tab.path}/`);
              return (
                <button
                  key={tab.key}
                  type="button"
                  className={`nav-link ${active ? 'active' : ''} ${tab.complete ? 'done' : ''}`}
                  disabled={!tab.enabled}
                  onClick={() => {
                    if (!tab.enabled) return;
                    navigate(tab.path);
                  }}
                  aria-current={active ? 'page' : undefined}
                >
                  {tab.label}
                  {tab.complete ? <Check size={12} /> : null}
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      <motion.main
        key={location.pathname}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.32, ease: 'easeOut' }}
      >
        <Suspense
          fallback={(
            <StateMessage
              variant="loading"
              title="Preparing your workspace"
              detail="Loading the next view with the latest execution context."
            />
          )}
        >
          <Routes>
            <Route path="/" element={<UploadPage />} />
            <Route path="/analysis/:projectId" element={<AnalysisPage />} />
            <Route path="/deployment/:projectId" element={<DeploymentPage />} />
            <Route path="/dashboard/:projectId" element={<DashboardPage />} />
            <Route path="*" element={<UploadPage />} />
          </Routes>
        </Suspense>
      </motion.main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppFrame />
    </BrowserRouter>
  );
}
