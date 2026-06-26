// src/features/chat/useAtFileQuery.ts
/**
 * 提取文本中光标位置前的 @文件引用查询
 *
 * 规则:
 * - 从光标位置向前扫描, 遇到空白字符停止
 * - 如果找到 @, 检查前一个字符是否为空白或字符串开头
 * - 只有 @ 前为空白或开头时, 才认为是有效的文件引用触发
 *
 * @param input - 完整输入文本
 * @param cursorPos - 光标位置 (0-based)
 * @returns 查询结果: query (提取的文本), startIdx/endIdx (@符号到光标的位置)
 */
export function useAtFileQuery(
  input: string,
  cursorPos: number,
): { query: string | null; startIdx: number; endIdx: number } {
  let i = cursorPos - 1;

  // 向前扫描, 遇到空白停止
  while (i >= 0 && !/\s/.test(input[i])) {
    if (input[i] === '@') {
      // 检查 @ 前是否为空白或开头
      if (i === 0 || /\s/.test(input[i - 1])) {
        const query = input.slice(i + 1, cursorPos);
        return { query, startIdx: i, endIdx: cursorPos };
      }
      // @ 前不是空白, 不是有效触发
      break;
    }
    i--;
  }

  return { query: null, startIdx: 0, endIdx: 0 };
}
