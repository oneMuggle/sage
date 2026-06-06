import { Skeleton } from './Skeleton';

export function MessageSkeleton() {
  return (
    <div className="flex gap-2 p-3" role="status" aria-label="加载消息中">
      <Skeleton circle width="2rem" height="2rem" />
      <div className="flex-1 flex flex-col gap-2">
        <Skeleton width="20%" height="0.75rem" />
        <Skeleton width="100%" height="0.875rem" />
        <Skeleton width="90%" height="0.875rem" />
        <Skeleton width="40%" height="0.875rem" />
      </div>
    </div>
  );
}
