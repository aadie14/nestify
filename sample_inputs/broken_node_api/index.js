const express = require("express");
const app = express();

app.get("/", (req, res) => {
  // Intentional bug: missing environment variable should trigger deployment/runtime issue.
  if (!process.env.DATABASE_URL) {
    throw new Error("DATABASE_URL is required");
  }
  res.json({ ok: true });
});

app.listen(process.env.PORT || 3000, () => {
  console.log("Server started");
});
