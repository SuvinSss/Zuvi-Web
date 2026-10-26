import { StoreLocationEditor } from "../../components/StoreLocationEditor";
import { ErrorRetry, Loading } from "../../components/ui";
import { get } from "../../lib/api";
import { useLoad } from "../../lib/useAsync";
import type { StoreLocation } from "../../lib/types";

export function StoreLocationPage() {
  const s = useLoad(() => get<StoreLocation>("/store/location/"));
  if (s.loading) return <Loading />;
  if (s.error) return <ErrorRetry message={s.error} onRetry={s.reload} />;
  if (!s.data) return null;
  return (
    <div>
      <h1>{s.data.name}: pickup location</h1>
      <p className="muted">Riders navigate to this pin and customers' delivery fees are measured from it.</p>
      <div className="card">
        <StoreLocationEditor store={s.data} endpoint="/store/location/" allowRadius={false} onSaved={(u) => s.setData(u)} />
      </div>
    </div>
  );
}
