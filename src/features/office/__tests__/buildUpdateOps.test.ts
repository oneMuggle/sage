import { describe, expect, it } from 'vitest';

import { buildUpdateOps } from '../OfficeEditPreviewDialog';

describe('buildUpdateOps — op composition table', () => {
  // F2 (office-p0): ComposeState gained op-kind selectors + per-kind
  // fields; this base mirrors INITIAL_COMPOSE (default kinds) so the
  // legacy single-op cases keep exercising the same code paths.
  const base = {
    wordKind: 'replace_text' as const,
    excelKind: 'set_cells' as const,
    pptKind: 'set_slide_title' as const,
    find: '',
    replace: '',
    paragraphsText: '',
    paraHeading: '' as '' | 'h1' | 'h2' | 'h3',
    tableIndex: '0',
    tableRow: '',
    tableCol: '',
    tableText: '',
    deleteFind: '',
    deleteAll: false,
    commentText: '',
    commentAuthor: '',
    chartType: 'bar' as const,
    chartAnchor: '',
    chartMinCol: '',
    chartMinRow: '',
    chartMaxCol: '',
    chartMaxRow: '',
    chartTitle: '',
    colWidthColumn: '',
    colWidthValue: '',
    fillCells: '',
    fillColor: '',
    freezeCell: '',
    numFormatCells: '',
    numFormatValue: '',
    styleMatch: '',
    styleIndex: '',
    styleFontSize: '',
    styleBold: false,
    styleItalic: false,
    styleColor: '',
    styleAlign: '',
    commentId: '',
    imagePath: '',
    imageWidth: '',
    imageHeight: '',
    sheet: '',
    cell: '',
    value: '',
    rowsText: '',
    slideNumber: '1',
    slideTitle: '',
    bulletsText: '',
    notesText: '',
    appendTitle: '',
    appendNotes: '',
    pictureIndex: '1',
    picturePath: '',
    pictureWidth: '',
    pictureHeight: '',
  };

  it('word: requires find; empty replace means delete', () => {
    expect(buildUpdateOps('word', base)).toBeNull();
    expect(buildUpdateOps('word', { ...base, find: ' x ', replace: '' })).toEqual([
      { op: 'replace_text', find: 'x', replace: '' },
    ]);
  });

  it('excel: requires sheet, addr and value', () => {
    expect(buildUpdateOps('excel', { ...base, sheet: 'S' })).toBeNull();
    expect(buildUpdateOps('excel', { ...base, sheet: 'S', cell: 'B2', value: ' v ' })).toEqual([
      { op: 'set_cells', sheet: 'S', cells: [{ addr: 'B2', value: 'v' }] },
    ]);
  });

  it('ppt: 1-based number → 0-based index; rejects 0 and non-integers', () => {
    expect(buildUpdateOps('ppt', { ...base, slideNumber: '0', slideTitle: 't' })).toBeNull();
    expect(buildUpdateOps('ppt', { ...base, slideNumber: 'abc', slideTitle: 't' })).toBeNull();
    expect(buildUpdateOps('ppt', { ...base, slideNumber: '2', slideTitle: ' t ' })).toEqual([
      { op: 'set_slide_title', index: 1, title: 't' },
    ]);
  });

  it('word set_paragraph_style: locator + at least one style prop', () => {
    expect(buildUpdateOps('word', { ...base, wordKind: 'set_paragraph_style' })).toBeNull();
    expect(
      buildUpdateOps('word', {
        ...base,
        wordKind: 'set_paragraph_style',
        styleMatch: '旧文本',
        styleFontSize: '14',
        styleBold: true,
        styleColor: ' FF0000 ',
        styleAlign: 'center',
      }),
    ).toEqual([
      {
        op: 'set_paragraph_style',
        match: '旧文本',
        font_size: 14,
        bold: true,
        color: 'FF0000',
        align: 'center',
      },
    ]);
    expect(
      buildUpdateOps('word', {
        ...base,
        wordKind: 'set_paragraph_style',
        styleIndex: '3',
        styleItalic: true,
      }),
    ).toEqual([{ op: 'set_paragraph_style', index: 3, italic: true }]);
    // 非法 index / 无样式属性 → null
    expect(
      buildUpdateOps('word', {
        ...base,
        wordKind: 'set_paragraph_style',
        styleIndex: '-1',
        styleItalic: true,
      }),
    ).toBeNull();
  });

  it('word delete_comment: comment_id required', () => {
    expect(buildUpdateOps('word', { ...base, wordKind: 'delete_comment' })).toBeNull();
    expect(
      buildUpdateOps('word', { ...base, wordKind: 'delete_comment', commentId: ' 2 ' }),
    ).toEqual([{ op: 'delete_comment', comment_id: '2' }]);
  });

  it('excel add_chart: type/anchor/data_ref validation', () => {
    expect(
      buildUpdateOps('excel', {
        ...base,
        excelKind: 'add_chart',
        sheet: 'S',
        chartType: 'bar',
        chartAnchor: ' a10 ',
        chartMinCol: '1',
        chartMinRow: '2',
        chartMaxCol: '3',
        chartMaxRow: '4',
      }),
    ).toEqual([
      {
        op: 'add_chart',
        sheet: 'S',
        type: 'bar',
        anchor: 'A10',
        data_ref: { min_col: 1, min_row: 2, max_col: 3, max_row: 4 },
      },
    ]);
    expect(
      buildUpdateOps('excel', {
        ...base,
        excelKind: 'add_chart',
        sheet: 'S',
        chartType: 'pie',
        chartAnchor: 'B2',
        chartMinCol: '2',
        chartMinRow: '2',
        chartMaxCol: '1',
        chartMaxRow: '4',
      }),
    ).toBeNull(); // min>max 拒绝
    expect(
      buildUpdateOps('excel', {
        ...base,
        excelKind: 'add_chart',
        sheet: 'S',
        chartType: 'line',
        chartAnchor: 'A1',
        chartMinCol: 'x',
        chartMinRow: '2',
        chartMaxCol: '3',
        chartMaxRow: '4',
      }),
    ).toBeNull(); // 非整数拒绝
  });

  it('excel set_column_width / set_fill / freeze_panes validation', () => {
    expect(
      buildUpdateOps('excel', {
        ...base,
        excelKind: 'set_column_width',
        sheet: 'S',
        colWidthColumn: ' a ',
        colWidthValue: '18.5',
      }),
    ).toEqual([{ op: 'set_column_width', sheet: 'S', column: 'A', width: 18.5 }]);
    expect(
      buildUpdateOps('excel', {
        ...base,
        excelKind: 'set_column_width',
        sheet: 'S',
        colWidthColumn: 'A',
        colWidthValue: '-1',
      }),
    ).toBeNull();
    expect(
      buildUpdateOps('excel', {
        ...base,
        excelKind: 'set_fill',
        sheet: 'S',
        fillCells: ' b2:b10 ',
        fillColor: '#FFD966',
      }),
    ).toEqual([{ op: 'set_fill', sheet: 'S', cells: 'B2:B10', color: 'FFD966' }]);
    expect(
      buildUpdateOps('excel', {
        ...base,
        excelKind: 'set_fill',
        sheet: 'S',
        fillCells: 'B2',
        fillColor: 'red',
      }),
    ).toBeNull(); // 非 hex 拒绝
    expect(
      buildUpdateOps('excel', {
        ...base,
        excelKind: 'freeze_panes',
        sheet: 'S',
        freezeCell: ' b2 ',
      }),
    ).toEqual([{ op: 'freeze_panes', sheet: 'S', cell: 'B2' }]);
  });

  it('excel set_number_format: cells + format required', () => {
    expect(
      buildUpdateOps('excel', {
        ...base,
        excelKind: 'set_number_format',
        sheet: 'S',
        numFormatCells: ' b2:b10 ',
        numFormatValue: ' 0.00% ',
      }),
    ).toEqual([{ op: 'set_number_format', sheet: 'S', cells: 'B2:B10', format: '0.00%' }]);
    expect(
      buildUpdateOps('excel', {
        ...base,
        excelKind: 'set_number_format',
        sheet: 'S',
        numFormatCells: 'B2',
      }),
    ).toBeNull();
  });

  it('word add_image: path required, optional inch dims', () => {
    expect(buildUpdateOps('word', { ...base, wordKind: 'add_image' })).toBeNull();
    expect(
      buildUpdateOps('word', {
        ...base,
        wordKind: 'add_image',
        imagePath: ' images/logo.png ',
        imageWidth: '4',
        imageHeight: '3',
      }),
    ).toEqual([{ op: 'add_image', path: 'images/logo.png', width_inches: 4, height_inches: 3 }]);
    expect(
      buildUpdateOps('word', {
        ...base,
        wordKind: 'add_image',
        imagePath: 'images/logo.png',
      }),
    ).toEqual([{ op: 'add_image', path: 'images/logo.png' }]);
  });

  it('ppt add_picture: 1-based slide + path required, optional dims', () => {
    expect(buildUpdateOps('ppt', { ...base, pptKind: 'add_picture' })).toBeNull();
    expect(
      buildUpdateOps('ppt', {
        ...base,
        pptKind: 'add_picture',
        pictureIndex: '2',
        picturePath: ' images/logo.png ',
        pictureWidth: '6',
        pictureHeight: '4.5',
      }),
    ).toEqual([
      {
        op: 'add_picture',
        index: 1,
        path: 'images/logo.png',
        width_inches: 6,
        height_inches: 4.5,
      },
    ]);
    expect(
      buildUpdateOps('ppt', {
        ...base,
        pptKind: 'add_picture',
        pictureIndex: '0',
        picturePath: 'x',
      }),
    ).toBeNull();
  });

  it('pdf is not editable via this dialog', () => {
    expect(buildUpdateOps('pdf', { ...base, find: 'x' })).toBeNull();
  });

  // ── F2 (office-p0): op-kind selector exposes more backend ops ──────

  it('word append_paragraphs: lines → paragraphs, optional heading', () => {
    expect(buildUpdateOps('word', { ...base, wordKind: 'append_paragraphs' })).toBeNull();
    expect(
      buildUpdateOps('word', {
        ...base,
        wordKind: 'append_paragraphs',
        paragraphsText: '第一段\n\n第二段 ',
      }),
    ).toEqual([
      {
        op: 'append_paragraphs',
        paragraphs: [{ text: '第一段' }, { text: '第二段' }],
      },
    ]);
    expect(
      buildUpdateOps('word', {
        ...base,
        wordKind: 'append_paragraphs',
        paragraphsText: '标题段',
        paraHeading: 'h2',
      }),
    ).toEqual([{ op: 'append_paragraphs', paragraphs: [{ text: '标题段', heading: 'h2' }] }]);
  });

  it('word set_table_cell: integer indices + non-empty text required', () => {
    expect(
      buildUpdateOps('word', {
        ...base,
        wordKind: 'set_table_cell',
        tableRow: '1',
        tableCol: '2',
        tableText: '新值',
      }),
    ).toEqual([{ op: 'set_table_cell', table_index: 0, row: 1, col: 2, text: '新值' }]);
    expect(
      buildUpdateOps('word', {
        ...base,
        wordKind: 'set_table_cell',
        tableRow: '1.5',
        tableCol: '2',
        tableText: 'x',
      }),
    ).toBeNull();
    expect(
      buildUpdateOps('word', {
        ...base,
        wordKind: 'set_table_cell',
        tableRow: '1',
        tableCol: '2',
        tableText: '',
      }),
    ).toBeNull();
  });

  it('word delete_paragraph: find required; all flag forwarded', () => {
    expect(buildUpdateOps('word', { ...base, wordKind: 'delete_paragraph' })).toBeNull();
    expect(
      buildUpdateOps('word', { ...base, wordKind: 'delete_paragraph', deleteFind: ' 旧句 ' }),
    ).toEqual([{ op: 'delete_paragraph', find: '旧句' }]);
    expect(
      buildUpdateOps('word', {
        ...base,
        wordKind: 'delete_paragraph',
        deleteFind: '旧句',
        deleteAll: true,
      }),
    ).toEqual([{ op: 'delete_paragraph', find: '旧句', all: true }]);
  });

  it('word add_comment: find + comment required, optional author', () => {
    expect(buildUpdateOps('word', { ...base, wordKind: 'add_comment' })).toBeNull();
    expect(
      buildUpdateOps('word', {
        ...base,
        wordKind: 'add_comment',
        deleteFind: '旧句',
        commentText: ' 这里要补引用 ',
        commentAuthor: '张三',
      }),
    ).toEqual([{ op: 'add_comment', find: '旧句', comment: '这里要补引用', author: '张三' }]);
    expect(
      buildUpdateOps('word', {
        ...base,
        wordKind: 'add_comment',
        deleteFind: '旧句',
        commentText: '批注',
      }),
    ).toEqual([{ op: 'add_comment', find: '旧句', comment: '批注' }]);
  });

  it('excel append_rows: csv lines → rows', () => {
    expect(buildUpdateOps('excel', { ...base, excelKind: 'append_rows', sheet: 'S' })).toBeNull();
    expect(
      buildUpdateOps('excel', {
        ...base,
        excelKind: 'append_rows',
        sheet: ' S ',
        rowsText: '苹果, 3\n香蕉,12',
      }),
    ).toEqual([
      {
        op: 'append_rows',
        sheet: 'S',
        rows: [
          ['苹果', '3'],
          ['香蕉', '12'],
        ],
      },
    ]);
  });

  it('ppt set_slide_bullets / set_slide_notes / append_slide', () => {
    expect(
      buildUpdateOps('ppt', {
        ...base,
        pptKind: 'set_slide_bullets',
        slideNumber: '2',
        bulletsText: '甲\n乙',
      }),
    ).toEqual([{ op: 'set_slide_bullets', index: 1, bullets: ['甲', '乙'] }]);
    expect(
      buildUpdateOps('ppt', {
        ...base,
        pptKind: 'set_slide_bullets',
        slideNumber: '2',
      }),
    ).toBeNull();
    expect(
      buildUpdateOps('ppt', {
        ...base,
        pptKind: 'set_slide_notes',
        slideNumber: '1',
        notesText: ' 口播备注 ',
      }),
    ).toEqual([{ op: 'set_slide_notes', index: 0, notes: '口播备注' }]);
    expect(
      buildUpdateOps('ppt', {
        ...base,
        pptKind: 'append_slide',
        appendTitle: '结尾页',
        bulletsText: '总结\nQ&A',
        appendNotes: ' 感谢聆听 ',
      }),
    ).toEqual([
      {
        op: 'append_slide',
        title: '结尾页',
        bullets: ['总结', 'Q&A'],
        notes: '感谢聆听',
      },
    ]);
    expect(buildUpdateOps('ppt', { ...base, pptKind: 'append_slide' })).toBeNull();
  });
});
