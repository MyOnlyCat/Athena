import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Statistic } from "antd";

import { apiMessage, overviewApi } from "../../shared/api/client";

const REFRESH_INTERVAL_MS = 30_000;

export function DashboardPage() {
  const query = useQuery({
    queryKey: ["overview"],
    queryFn: overviewApi.get,
    refetchInterval: REFRESH_INTERVAL_MS
  });
  const overview = query.data;

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">MASTER OVERVIEW</p>
          <h1>系统概览</h1>
          <p>集中查看接入节点管理状态、连接状态和主机资产健康情况。</p>
        </div>
      </header>
      {query.error ? <Alert type="error" showIcon message={apiMessage(query.error)} /> : null}
      <section className="overview-section" aria-labelledby="management-summary">
        <h2 id="management-summary">接入节点管理</h2>
        <div className="overview-grid">
          <Card loading={query.isLoading}>
            <Statistic title="接入节点总数" value={overview?.nodes.total ?? 0} />
          </Card>
          <Card loading={query.isLoading}>
            <Statistic title="待审批" value={overview?.nodes.pending ?? 0} />
          </Card>
          <Card loading={query.isLoading}>
            <Statistic title="已启用" value={overview?.nodes.active ?? 0} />
          </Card>
          <Card loading={query.isLoading}>
            <Statistic title="已禁用" value={overview?.nodes.disabled ?? 0} />
          </Card>
          <Card loading={query.isLoading}>
            <Statistic title="已拒绝" value={overview?.nodes.rejected ?? 0} />
          </Card>
        </div>
      </section>
      <section className="overview-section" aria-labelledby="connectivity-summary">
        <h2 id="connectivity-summary">接入节点连接状态</h2>
        <div className="overview-grid overview-grid-compact">
          <Card loading={query.isLoading}>
            <Statistic title="在线" value={overview?.nodes.online ?? 0} />
          </Card>
          <Card loading={query.isLoading}>
            <Statistic title="心跳延迟" value={overview?.nodes.stale ?? 0} />
          </Card>
          <Card loading={query.isLoading}>
            <Statistic title="离线" value={overview?.nodes.offline ?? 0} />
          </Card>
        </div>
      </section>
      <section className="overview-section" aria-labelledby="asset-summary">
        <h2 id="asset-summary">主机资产健康</h2>
        <div className="overview-grid overview-grid-compact">
          <Card loading={query.isLoading}>
            <Statistic title="在管资产总数" value={overview?.assets.active ?? 0} />
          </Card>
          <Card loading={query.isLoading}>
            <Statistic title="明确异常资产" value={overview?.assets.abnormal ?? 0} />
          </Card>
          <Card loading={query.isLoading}>
            <Statistic title="状态未知资产" value={overview?.assets.unknown ?? 0} />
          </Card>
        </div>
      </section>
    </div>
  );
}
