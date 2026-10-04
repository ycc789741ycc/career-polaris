import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  Fit,
  OwnPosting,
  PlanSummary,
  ResumeSummary,
  Role,
  TargetRef,
} from "../api/types";
import {
  getPreviousTargets,
  getStoreWithUse,
  getStoredTargets,
  recordTargetUse,
  STORED_TARGET_LIMIT,
  type TargetStore,
} from "./advisorTarget";

const roleRef = (id: string): TargetRef => ({
  role_id: id,
  job_posting_id: null,
  private_job_posting_id: null,
});
const ownRef = (id: string): TargetRef => ({
  role_id: null,
  job_posting_id: null,
  private_job_posting_id: id,
});

const roles = [{ id: "r1" }, { id: "r2" }] as Role[];
const fits = [{ role_id: "r1", score: 81 }] as Fit[];
const own = [
  {
    private_job_posting_id: "j1",
    source: "uploaded",
    fit: 71,
    is_stale: false,
  },
  {
    private_job_posting_id: "j2",
    source: "filled_in",
    fit: null,
    is_stale: false,
  },
] as OwnPosting[];

function plan(target: TargetRef, label: string, at: string): PlanSummary {
  return {
    target,
    label,
    created_at: at,
    drafted_at: at,
  } as PlanSummary;
}

function resume(target: TargetRef, label: string, at: string): ResumeSummary {
  return { target, label, updated_at: at } as ResumeSummary;
}

const none = { plans: [], resumes: [], roles, fits, own, current: null };

describe("the targets a browser remembers", () => {
  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("makes a used target the current one and the newest, once", () => {
    const first = getStoreWithUse(
      { current: null, history: [] },
      roleRef("r1"),
      "Backend",
      new Date("2026-09-01T00:00:00Z"),
    );
    const second = getStoreWithUse(
      first,
      roleRef("r2"),
      "Platform",
      new Date("2026-09-02T00:00:00Z"),
    );
    const again = getStoreWithUse(
      second,
      roleRef("r1"),
      "Backend",
      new Date("2026-09-03T00:00:00Z"),
    );

    expect(again.current).toEqual(roleRef("r1"));
    expect(again.history.map((use) => [use.label, use.usedAt])).toEqual([
      ["Backend", "2026-09-03T00:00:00.000Z"],
      ["Platform", "2026-09-02T00:00:00.000Z"],
    ]);
  });

  it("keeps only the newest few", () => {
    let store: TargetStore = { current: null, history: [] };
    for (let i = 0; i < STORED_TARGET_LIMIT + 5; i += 1) {
      store = getStoreWithUse(store, roleRef(`r${i}`), `Role ${i}`, new Date());
    }
    expect(store.history).toHaveLength(STORED_TARGET_LIMIT);
    expect(store.history[0]!.label).toBe(`Role ${STORED_TARGET_LIMIT + 4}`);
  });

  it("keeps each account's apart", () => {
    recordTargetUse("maya@example.com", roleRef("r1"), "Backend");

    expect(getStoredTargets("maya@example.com").current).toEqual(roleRef("r1"));
    expect(getStoredTargets("sam@example.com").current).toBeNull();
    expect(getStoredTargets(null).current).toBeNull();
  });

  it("reads nothing when storage fails or holds something else", () => {
    window.localStorage.setItem("careerpolaris.target.maya@example.com", "{");
    expect(getStoredTargets("maya@example.com")).toEqual({
      current: null,
      history: [],
    });

    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(getStoredTargets("maya@example.com").history).toEqual([]);
  });

  it("does not fail when storage refuses a write", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() =>
      recordTargetUse("maya@example.com", roleRef("r1"), "Backend"),
    ).not.toThrow();
  });
});

describe("previous targets", () => {
  it("joins what this browser used with what the server wrote, dated by the latest", () => {
    const previous = getPreviousTargets({
      ...none,
      history: [
        { ref: roleRef("r1"), label: "Backend", usedAt: "2026-09-05T00:00:00Z" },
      ],
      plans: [plan(roleRef("r1"), "Backend", "2026-09-10T00:00:00Z")],
      resumes: [resume(ownRef("j1"), "Principal · Halden", "2026-09-12T00:00:00Z")],
    });

    expect(previous).toEqual([
      {
        ref: ownRef("j1"),
        label: "Principal · Halden",
        source: "own_role",
        detail: "uploaded JD",
        lastUsedAt: "2026-09-12T00:00:00Z",
        fit: 71,
      },
      {
        ref: roleRef("r1"),
        label: "Backend",
        source: "role_map",
        detail: null,
        lastUsedAt: "2026-09-10T00:00:00Z",
        fit: 81,
      },
    ]);
  });

  it("leaves out the current target and any that can no longer be aimed at", () => {
    const previous = getPreviousTargets({
      ...none,
      current: roleRef("r1"),
      history: [
        { ref: roleRef("r1"), label: "Current", usedAt: "2026-09-05T00:00:00Z" },
        { ref: roleRef("gone"), label: "Gone", usedAt: "2026-09-05T00:00:00Z" },
        { ref: ownRef("j2"), label: "Not scored", usedAt: "2026-09-05T00:00:00Z" },
        { ref: ownRef("removed"), label: "Removed", usedAt: "2026-09-05T00:00:00Z" },
        { ref: roleRef("r2"), label: "Platform", usedAt: "2026-09-04T00:00:00Z" },
      ],
    });

    expect(previous.map((target) => [target.label, target.fit])).toEqual([
      ["Platform", null],
    ]);
  });

  it("shows no fit for a role of your own scored against an older analysis", () => {
    const previous = getPreviousTargets({
      ...none,
      own: [{ ...own[0]!, is_stale: true }],
      history: [
        { ref: ownRef("j1"), label: "Principal", usedAt: "2026-09-05T00:00:00Z" },
      ],
    });

    expect(previous[0]!.fit).toBeNull();
  });
});
