import { AppIcon } from "../components/AppIcon";
import { isBusy, sourcesBusy, useActivity } from "./activity";
import { JOURNEY, MODEL_SCREEN, type Screen } from "./navigation";
import {
  getPlatformQuota,
  getQuotaLabel,
  hasAi,
  isOnPlatform,
  modelName,
  type ShellStatus,
} from "./ShellContext";

/** The prototype's left rail: the numbered journey and the model. Profile
 * confidence belongs to Strengths (domain decision 28). */
export function Sidebar({
  current,
  status,
  onNavigate,
}: {
  current: Screen;
  status: ShellStatus;
  onNavigate: (screen: Screen) => void;
}) {
  const noKey = !hasAi(status);
  const keyFailed =
    !isOnPlatform(status) && status.credential?.status === "failed";
  const quota = getPlatformQuota(status);
  const quotaUsed = quota ? getQuotaLabel(quota).used : null;
  const quotaGone = quotaUsed !== null && quotaUsed >= 100;
  const { activity } = useActivity();
  const running: Partial<Record<Screen, boolean>> = {
    sources: sourcesBusy(activity),
    strengths: isBusy(activity?.analysis),
    roles: isBusy(activity?.role_map),
  };

  return (
    <aside className="sidebar">
      <div className="brand">
        <AppIcon size={28} />
        CareerPolaris
      </div>

      <nav aria-label="Screens">
        <ul className="nav-list">
          {JOURNEY.map((item) => {
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className="nav-item"
                  aria-current={current === item.id ? "page" : undefined}
                  onClick={() => onNavigate(item.id)}
                >
                  <span className="nav-num" aria-hidden="true">
                    {item.num}
                  </span>
                  {item.label}
                  {running[item.id] && (
                    <span
                      className="nav-running"
                      role="img"
                      aria-label="running"
                    />
                  )}
                </button>
              </li>
            );
          })}
        </ul>

        <div className="sidebar-section">
          <div className="eyebrow">System configuration</div>
          <button
            type="button"
            className="nav-item"
            style={{ padding: "8px 10px" }}
            aria-current={current === MODEL_SCREEN.id ? "page" : undefined}
            onClick={() => onNavigate(MODEL_SCREEN.id)}
          >
            <span className="nav-ring" aria-hidden="true" />
            <span style={{ minWidth: 0 }}>
              {MODEL_SCREEN.label}
              <span className="nav-note">
                {noKey
                  ? "No key yet"
                  : quotaUsed !== null
                    ? `${modelName(status)} · ${quotaUsed}% of free quota used`
                    : isOnPlatform(status)
                      ? `${modelName(status)} · CareerPolaris AI`
                      : `${modelName(status)}${keyFailed ? " · key failed" : ""}`}
              </span>
            </span>
            {(noKey || keyFailed || quotaGone) && (
              <span
                className="nav-flag"
                aria-label={
                  noKey
                    ? "needs a key"
                    : keyFailed
                      ? "key failed"
                      : "free quota used up"
                }
              >
                !
              </span>
            )}
          </button>
        </div>
      </nav>
    </aside>
  );
}
