from locust import HttpUser, task, between

class NestifyLoadTest(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def check_status(self):
        # Polling a sample project ID (e.g. 69 or 71 from recent history)
        self.client.get("/api/status/71", name="/api/status/{id}")

    @task(1)
    def check_stats(self):
        # Fetching agentic stats
        self.client.get("/api/v1/agentic/stats", name="/api/v1/agentic/stats")

    @task(1)
    def check_patterns(self):
        # Fetching patterns for project
        self.client.get("/api/v1/agentic/patterns/71", name="/api/v1/agentic/patterns/{id}")
