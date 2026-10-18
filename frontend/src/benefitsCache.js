// One shared copy of the benefits check, so moving between Home, Benefits,
// the application pack and a letter doesn't redo it (each check runs the
// rules and explains every program). Anything that can change the answer
// -- a saved letter, an answered question, an application answer, the QMB
// switch, deleting data, signing out -- calls invalidateBenefits() (api.js).
const FRESH_MS = 5 * 60 * 1000;
let cache = null; // { key, promise, at }

export function invalidateBenefits() {
  cache = null;
}

export function cachedBenefits(key, load, force) {
  const fresh = cache && cache.key === key && Date.now() - cache.at < FRESH_MS;
  if (!force && fresh) return cache.promise;
  const entry = { key, at: Date.now() };
  entry.promise = load().catch((error) => {
    if (cache === entry) cache = null; // never keep a failure
    throw error;
  });
  cache = entry;
  return entry.promise;
}
