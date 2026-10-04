import type { Activity } from "../api/types";

/** The worker and the crawler up: what every test means unless it says. */
export const ONLINE: Activity["processing"] = {
  is_worker_online: true,
  is_crawler_online: true,
  worker_seen_at: "2026-09-28T09:00:00Z",
  crawler_seen_at: "2026-09-28T09:00:00Z",
};

/** The machine that runs background work is off (ADR 0052). */
export const AWAY: Activity["processing"] = {
  is_worker_online: false,
  is_crawler_online: false,
  worker_seen_at: "2026-09-27T22:00:00Z",
  crawler_seen_at: "2026-09-27T22:00:00Z",
};
