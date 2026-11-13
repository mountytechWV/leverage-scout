// Leverage Scout service worker: lets browsers offer "Install app".
// Always fetches fresh data from the network so the ETF list is never stale.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
