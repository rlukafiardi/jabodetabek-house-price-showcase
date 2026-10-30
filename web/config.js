// Set apiBase to the deployed estimate service (no trailing slash), e.g. "https://estimate-xxxx.a.run.app".
// While it is empty the map works and the estimate form says the service is not connected yet.
// For local testing, open the page on localhost with ?api=http://localhost:8080 (run `make api` with ALLOWED_ORIGINS set to the page's origin).
export const CONFIG = { apiBase: "" };
