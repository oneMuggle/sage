import { LaneBoard } from '../widgets/orchestration/LaneBoard';

export function Orchestration() {
  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-7xl mx-auto px-6 py-6">
        <h1 className="text-2xl font-semibold mb-6">Orchestration Board</h1>
        <LaneBoard />
      </div>
    </div>
  );
}
