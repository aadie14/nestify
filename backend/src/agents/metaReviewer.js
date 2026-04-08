s/**
 * Meta Reviewer Agent — The Double-Checker (Second Opinion).
 * 
 * Independently reviews ALL outputs from other agents.
 * Must issue a PASS/FAIL before deployment is allowed.
 */

const { callLLM } = require('../services/llmService');

/**
 * Perform a full independent review of the generated Docker stack.
 * @param {Object} params
 * @param {Object} params.stackSummary - From Stack Analyzer
 * @param {string} params.dockerfile - From Docker Architect
 * @param {string} params.compose - From Docker Architect
 * @param {string} params.envTemplate - Generated .env.example
 * @param {Object} params.securityReport - From Safety Guard
 * @returns {Promise<Object>} Meta review result
 */
async function review({ stackSummary, dockerfile, compose, envTemplate, securityReport }) {
    const prompt = `You are a senior DevOps engineer performing a final review before deployment.

You are reviewing outputs from THREE other AI agents:
1. Stack Analyzer detected: ${stackSummary.runtime} / ${stackSummary.framework} / port ${stackSummary.port}
2. Docker Architect generated the Dockerfile and docker-compose.yml
3. Safety Guard performed a security scan

Your job is to INDEPENDENTLY verify:
- Does the Dockerfile match what the Stack Analyzer detected?
- Is the port in the Dockerfile consistent with the detected port?
- Does docker-compose.yml include ALL detected databases?
- Are ALL detected env vars present in the .env template?
- Do you agree with the Security Guard's assessment?
- Are there any cross-agent inconsistencies or errors the others missed?

STACK ANALYSIS:
${JSON.stringify(stackSummary, null, 2)}

DOCKERFILE:
${dockerfile}

DOCKER-COMPOSE.YML:
${compose}

.ENV TEMPLATE:
${envTemplate}

SECURITY REPORT:
${JSON.stringify(securityReport, null, 2)}

Return ONLY valid JSON:
{
  "verdict": "PASS" or "FAIL",
  "score": 1-10,
  "issues": [
    {
      "severity": "critical|high|medium|low",
      "agent": "which agent made the mistake",
      "description": "what's wrong",
      "suggestedFix": "how to fix it"
    }
  ],
  "summary": "2-3 sentence overall assessment in plain English",
  "confidence": 0.0-1.0
}`;

    const result = await callLLM(
        [
            { role: 'system', content: 'You are a senior DevOps reviewer. Be critical but fair. Return only valid JSON. No markdown.' },
            { role: 'user', content: prompt },
        ],
        { taskWeight: 'heavy', jsonMode: true, temperature: 0.1 }
    );

    let parsed;
    try {
        parsed = JSON.parse(result.content);
    } catch {
        const match = result.content.match(/\{[\s\S]*\}/);
        if (match) {
            parsed = JSON.parse(match[0]);
        } else {
            throw new Error('Meta Reviewer failed to return valid JSON');
        }
    }

    return {
        verdict: parsed.verdict || 'FAIL',
        score: parsed.score || 0,
        issues: parsed.issues || [],
        summary: parsed.summary || 'Review could not be completed.',
        confidence: parsed.confidence || 0,
        tokensUsed: result.tokensUsed,
    };
}

module.exports = { review };
