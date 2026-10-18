import { useRef } from "react";
import { fetchBenefits } from "../api";
import { cachedBenefits } from "../benefitsCache";
import { useLoad } from "./useLoad";

// useLoad for the benefits check, sharing one copy across screens (see
// benefitsCache.js). reload() always asks the server again.
export function useBenefits(token, language) {
  const lang = language || "en";
  const forceRef = useRef(false);
  const loaded = useLoad(() => {
    const force = forceRef.current;
    forceRef.current = false;
    return cachedBenefits(`${token}|${lang}`, () => fetchBenefits(token, lang), force);
  }, [token, lang]);
  return {
    ...loaded,
    reload: () => {
      forceRef.current = true;
      loaded.reload();
    },
  };
}
