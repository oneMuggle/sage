import { describe, expect, it } from 'vitest';
import { parseNDJSONStream } from '../llmStream';

describe('llmStream orchestration events', () => {
  it('parses task_plan events', async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            '{"state":"task_plan","run_id":"orch-1","plan":[{"task_id":"t1","agent_id":"researcher","goal":"调研"},{"task_id":"t2","agent_id":"writer","goal":"写作"}]}\n',
          ),
        );
        controller.close();
      },
    });
    const events = await collect(parseNDJSONStream(stream));
    expect(events[0].state).toBe('task_plan');
    if (events[0].state === 'task_plan') {
      expect(events[0].run_id).toBe('orch-1');
      expect(events[0].plan).toHaveLength(2);
    }
  });

  it('parses task_status events with all statuses', async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            '{"state":"task_status","run_id":"orch-1","task_id":"t1","status":"running","agent_id":"researcher","goal":"调研","error":null,"output_preview":null}\n',
          ),
        );
        controller.close();
      },
    });
    const events = await collect(parseNDJSONStream(stream));
    expect(events[0].state).toBe('task_status');
  });
});

async function collect<T>(iter: AsyncIterable<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const item of iter) out.push(item);
  return out;
}
