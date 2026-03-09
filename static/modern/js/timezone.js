(() => {
  const DEFAULT_TZ = "UTC";

  function normalizeTimezone(value) {
    const candidate = String(value || "").trim();
    if (!candidate) return DEFAULT_TZ;
    const upper = candidate.toUpperCase();
    if (["UTC", "GMT", "GMT+00:00", "Z"].includes(upper)) return DEFAULT_TZ;
    try {
      new Intl.DateTimeFormat("en-US", { timeZone: candidate });
      return candidate;
    } catch (_err) {
      return DEFAULT_TZ;
    }
  }

  function getDisplayTimezone() {
    return normalizeTimezone(
      window.BloomConfig?.user?.display_timezone || DEFAULT_TZ,
    );
  }

  function _coerceDate(value) {
    if (!value) return null;
    if (value instanceof Date) return value;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    return date;
  }

  function formatDateTime(value, options = {}) {
    const date = _coerceDate(value);
    if (!date) return "";
    return new Intl.DateTimeFormat("en-US", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      timeZone: getDisplayTimezone(),
      ...options,
    }).format(date);
  }

  window.BloomDateTime = {
    getDisplayTimezone,
    formatDateTime,
  };
})();
