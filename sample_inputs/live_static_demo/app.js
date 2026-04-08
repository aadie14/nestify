const btn = document.getElementById('pingBtn');
const status = document.getElementById('status');

btn.addEventListener('click', () => {
  const now = new Date().toLocaleString();
  status.textContent = `Runtime OK. Timestamp: ${now}`;
});
