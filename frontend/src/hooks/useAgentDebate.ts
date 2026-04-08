import { useEffect, useState } from 'react';
import axios from 'axios';

export type DebateRound = {
  round: number;
  type: string;
  statements?: Array<Record<string, unknown>>;
  decision?: Record<string, unknown>;
};

export function useAgentDebate(projectId: number | null) {
  const [rounds, setRounds] = useState<DebateRound[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    let alive = true;

    const load = async () => {
      try {
        setLoading(true);
        const res = await axios.get(`/api/v1/projects/${projectId}/report`);
        if (!alive) return;
        const transcriptFromInsights = res.data?.agentic_insights?.deployment_intelligence?.debate_transcript;
        const learning = Array.isArray(res.data?.learning) ? res.data.learning : [];
        const transcriptFromLearning = learning[0]?.debate_transcript;
        const transcript = Array.isArray(transcriptFromInsights) ? transcriptFromInsights : transcriptFromLearning;
        setRounds(Array.isArray(transcript) ? transcript : []);
      } catch {
        if (!alive) return;
        setRounds([]);
      } finally {
        if (alive) setLoading(false);
      }
    };

    load();
    return () => {
      alive = false;
    };
  }, [projectId]);

  return { rounds, loading };
}
