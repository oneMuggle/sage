import asyncio

from backend.orchestration.plan_progress import PLAN_STAGE_DECOMPOSE, run_planning_stage


def test_decompose_stage_describes_task_count():
    events = []

    async def emit(event):
        events.append(event)

    class _Plan:
        tasks = [1, 2, 3]

    async def runner():
        return _Plan()

    result = asyncio.run(
        run_planning_stage(
            emit,
            stage=PLAN_STAGE_DECOMPOSE,
            runner=runner,
            describe_result=lambda plan: (
                f"拆解为 {len(getattr(plan, 'tasks', []) or [])} 个任务"
            ),
        )
    )

    assert len(result.tasks) == 3
    assert events[-1]["plan_progress"]["text"] == "拆解为 3 个任务"
