import { Skeleton } from './Skeleton';

export function SessionListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div
      role="status"
      aria-label="加载会话列表中"
      className="flex flex-col gap-2 p-2"
    >
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-2 p-2">
          <Skeleton circle width="1.5rem" height="1.5rem" />
          <div className="flex-1 flex flex-col gap-1">
            <Skeleton width={`${50 + ((i * 10) % 40)}%`} height="0.875rem" />
            <Skeleton width="30%" height="0.625rem" />
          </div>
        </div>
      ))}
    </div>
  );
}
