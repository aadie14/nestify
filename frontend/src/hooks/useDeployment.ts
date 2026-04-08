import { useEffect, useState } from 'react';
import axios from 'axios';

type DeploymentResponse = {
  project?: {
    id?: number;
    status?: string;
    public_url?: string | null;
    agentic_insights?: Record<string, unknown> | null;
    deploy_provider?: string | null;
    deployment_details?: Record<string, unknown> | string | null;
  };
};

export function useDeployment(projectId: number | null) {
  const [deployment, setDeployment] = useState<DeploymentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let alive = true;

    const load = async () => {
      try {
        setLoading(true);
        setError(null);
        const res = await axios.get(`/api/status/${projectId}`);
        if (!alive) return;
        setDeployment(res.data);
      } catch (err: any) {
        if (!alive) return;
        const detail = err?.response?.data?.detail;
        if (typeof detail === 'string' && detail.trim()) {
          setError(`${detail.trim()} Next: verify backend connectivity and project status endpoint.`);
        } else {
          setError('Deployment state is unavailable. Next: check API health and retry.');
        }
      } finally {
        if (alive) setLoading(false);
      }
    };

    load();
    const timer = window.setInterval(load, 3000);

    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [projectId]);

  return { deployment, loading, error };
}
