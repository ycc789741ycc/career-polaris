import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useAsync } from "./useAsync";

/** A promise the test settles by hand. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useAsync", () => {
  it("loads once on mount and stops loading when it settles", async () => {
    let calls = 0;
    const { result } = renderHook(() =>
      useAsync(() => {
        calls += 1;
        return Promise.resolve("roles");
      }, []),
    );
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toBe("roles");
    expect(result.current.error).toBeNull();
    expect(calls).toBe(1);
  });

  it("loads again when deps change, keeping the old data meanwhile", async () => {
    const pending = { a: deferred<string>(), b: deferred<string>() };
    const { result, rerender } = renderHook(
      ({ key }: { key: "a" | "b" }) =>
        useAsync(() => pending[key].promise, [key]),
      { initialProps: { key: "a" as "a" | "b" } },
    );
    await act(async () => pending.a.resolve("first"));
    expect(result.current).toMatchObject({ data: "first", loading: false });

    rerender({ key: "b" });
    expect(result.current).toMatchObject({ data: "first", loading: true });

    await act(async () => pending.b.resolve("second"));
    expect(result.current).toMatchObject({ data: "second", loading: false });
  });

  it("drops a load whose deps have since changed", async () => {
    const pending = { a: deferred<string>(), b: deferred<string>() };
    const { result, rerender } = renderHook(
      ({ key }: { key: "a" | "b" }) =>
        useAsync(() => pending[key].promise, [key]),
      { initialProps: { key: "a" as "a" | "b" } },
    );
    rerender({ key: "b" });
    await act(async () => pending.b.resolve("newer"));
    await act(async () => pending.a.resolve("older"));
    expect(result.current).toMatchObject({ data: "newer", loading: false });
  });

  it("keeps the data and reports the error when a load fails", async () => {
    let shouldFail = false;
    const { result } = renderHook(() =>
      useAsync(
        () =>
          shouldFail
            ? Promise.reject(new Error("offline"))
            : Promise.resolve(3),
        [],
      ),
    );
    await waitFor(() => expect(result.current.data).toBe(3));

    shouldFail = true;
    await act(() => result.current.reload());
    expect(result.current).toMatchObject({
      data: 3,
      error: "offline",
      loading: false,
    });
  });

  it("is loading while a reload runs, and clears the error once it succeeds", async () => {
    let next = deferred<number>();
    const { result } = renderHook(() => useAsync(() => next.promise, []));
    await act(async () => next.resolve(1));

    act(() => result.current.setError("Could not save the cap"));
    expect(result.current.error).toBe("Could not save the cap");

    next = deferred<number>();
    let reloaded!: Promise<void>;
    act(() => {
      reloaded = result.current.reload();
    });
    expect(result.current.loading).toBe(true);

    await act(async () => {
      next.resolve(2);
      await reloaded;
    });
    expect(result.current).toMatchObject({
      data: 2,
      error: null,
      loading: false,
    });
  });
});
