from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_agentic_stats_endpoint_returns_expected_shape():
    response = client.get('/api/v1/agentic/stats')
    assert response.status_code == 200

    payload = response.json()
    assert 'total_deployments_analyzed' in payload
    assert 'patterns_discovered' in payload
    assert 'success_rate' in payload
    assert 'outcomes' in payload


def test_agentic_optimize_endpoint_executes_successfully_for_existing_project():
    response = client.post('/api/v1/agentic/optimize/1', json={})
    assert response.status_code == 200

    payload = response.json()
    assert payload.get('status') == 'ok'
    assert payload.get('project_id') == 1
    assert 'optimization' in payload
