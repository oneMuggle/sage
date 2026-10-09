import { useI18n } from '../../shared/lib/i18n';

import type { ComposeState, ExcelEditKind, PptEditKind } from './OfficeEditPreviewDialog';

export interface ExcelPptEditFormFieldsProps {
  docType: 'excel' | 'ppt';
  compose: ComposeState;
  setField: (key: keyof ComposeState) => (value: string) => void;
  inputClass: string;
  sheetNames?: string[];
}

export function ExcelPptEditFormFields({
  docType,
  compose,
  setField,
  inputClass,
  sheetNames,
}: ExcelPptEditFormFieldsProps) {
  const { t } = useI18n();
  if (docType === 'excel') {
    return (
              <div className="space-y-2" data-testid="office-edit-form-excel">
                <div>
                  <label className="block text-xs text-muted mb-1">{t('office.edit.opKind')}</label>
                  <select
                    value={compose.excelKind}
                    onChange={(e) => setField('excelKind')(e.target.value as ExcelEditKind)}
                    className={inputClass}
                    data-testid="office-edit-excel-kind"
                  >
                    <option value="set_cells">{t('office.edit.kindSetCells')}</option>
                    <option value="append_rows">{t('office.edit.kindAppendRows')}</option>
                    <option value="add_chart">{t('office.edit.kindAddChart')}</option>
                    <option value="set_column_width">{t('office.edit.kindSetColumnWidth')}</option>
                    <option value="set_fill">{t('office.edit.kindSetFill')}</option>
                    <option value="freeze_panes">{t('office.edit.kindFreezePanes')}</option>
                    <option value="set_number_format">
                      {t('office.edit.kindSetNumberFormat')}
                    </option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-muted mb-1">
                    {t('office.edit.excelSheet')}
                  </label>
                  {sheetNames && sheetNames.length > 0 ? (
                    <select
                      value={compose.sheet}
                      onChange={(e) => setField('sheet')(e.target.value)}
                      className={inputClass}
                      data-testid="office-edit-sheet"
                    >
                      {sheetNames.map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={compose.sheet}
                      onChange={(e) => setField('sheet')(e.target.value)}
                      className={inputClass}
                      data-testid="office-edit-sheet"
                    />
                  )}
                </div>
                {compose.excelKind === 'set_cells' && (
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.excelCell')}
                      </label>
                      <input
                        type="text"
                        value={compose.cell}
                        onChange={(e) => setField('cell')(e.target.value)}
                        placeholder={t('office.edit.excelCellPlaceholder')}
                        className={inputClass}
                        data-testid="office-edit-cell"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.excelValue')}
                      </label>
                      <input
                        type="text"
                        value={compose.value}
                        onChange={(e) => setField('value')(e.target.value)}
                        placeholder={t('office.edit.excelValuePlaceholder')}
                        className={inputClass}
                        data-testid="office-edit-value"
                      />
                    </div>
                  </div>
                )}
                {compose.excelKind === 'set_column_width' && (
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.colWidthColumn')}
                      </label>
                      <input
                        type="text"
                        value={compose.colWidthColumn}
                        onChange={(e) => setField('colWidthColumn')(e.target.value)}
                        placeholder="A"
                        className={inputClass}
                        data-testid="office-edit-col-width-column"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.colWidthValue')}
                      </label>
                      <input
                        type="number"
                        min={1}
                        step={0.5}
                        value={compose.colWidthValue}
                        onChange={(e) => setField('colWidthValue')(e.target.value)}
                        className={inputClass}
                        data-testid="office-edit-col-width-value"
                      />
                    </div>
                  </div>
                )}
                {compose.excelKind === 'set_fill' && (
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.fillCells')}
                      </label>
                      <input
                        type="text"
                        value={compose.fillCells}
                        onChange={(e) => setField('fillCells')(e.target.value)}
                        placeholder="B2:B10"
                        className={inputClass}
                        data-testid="office-edit-fill-cells"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.fillColor')}
                      </label>
                      <input
                        type="text"
                        value={compose.fillColor}
                        onChange={(e) => setField('fillColor')(e.target.value)}
                        placeholder="FFD966"
                        className={inputClass}
                        data-testid="office-edit-fill-color"
                      />
                    </div>
                  </div>
                )}
                {compose.excelKind === 'freeze_panes' && (
                  <div>
                    <label className="block text-xs text-muted mb-1">
                      {t('office.edit.freezeCell')}
                    </label>
                    <input
                      type="text"
                      value={compose.freezeCell}
                      onChange={(e) => setField('freezeCell')(e.target.value)}
                      placeholder="B2"
                      className={inputClass}
                      data-testid="office-edit-freeze-cell"
                    />
                  </div>
                )}
                {compose.excelKind === 'set_number_format' && (
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.fillCells')}
                      </label>
                      <input
                        type="text"
                        value={compose.numFormatCells}
                        onChange={(e) => setField('numFormatCells')(e.target.value)}
                        placeholder="B2:B10"
                        className={inputClass}
                        data-testid="office-edit-numfmt-cells"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.numFormatValue')}
                      </label>
                      <input
                        type="text"
                        value={compose.numFormatValue}
                        onChange={(e) => setField('numFormatValue')(e.target.value)}
                        placeholder="0.00%"
                        className={inputClass}
                        data-testid="office-edit-numfmt-value"
                      />
                    </div>
                  </div>
                )}
                {compose.excelKind === 'add_chart' && (
                  <>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.chartType')}
                        </label>
                        <select
                          value={compose.chartType}
                          onChange={(e) =>
                            setField('chartType')(e.target.value as ComposeState['chartType'])
                          }
                          className={inputClass}
                          data-testid="office-edit-chart-type"
                        >
                          <option value="bar">bar</option>
                          <option value="line">line</option>
                          <option value="pie">pie</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.chartAnchor')}
                        </label>
                        <input
                          type="text"
                          value={compose.chartAnchor}
                          onChange={(e) => setField('chartAnchor')(e.target.value)}
                          placeholder="A10"
                          className={inputClass}
                          data-testid="office-edit-chart-anchor"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-4 gap-2">
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.chartMinCol')}
                        </label>
                        <input
                          type="number"
                          min={1}
                          value={compose.chartMinCol}
                          onChange={(e) => setField('chartMinCol')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-chart-min-col"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.chartMinRow')}
                        </label>
                        <input
                          type="number"
                          min={1}
                          value={compose.chartMinRow}
                          onChange={(e) => setField('chartMinRow')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-chart-min-row"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.chartMaxCol')}
                        </label>
                        <input
                          type="number"
                          min={1}
                          value={compose.chartMaxCol}
                          onChange={(e) => setField('chartMaxCol')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-chart-max-col"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.chartMaxRow')}
                        </label>
                        <input
                          type="number"
                          min={1}
                          value={compose.chartMaxRow}
                          onChange={(e) => setField('chartMaxRow')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-chart-max-row"
                        />
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.chartTitle')}
                      </label>
                      <input
                        type="text"
                        value={compose.chartTitle}
                        onChange={(e) => setField('chartTitle')(e.target.value)}
                        className={inputClass}
                        data-testid="office-edit-chart-title"
                      />
                    </div>
                  </>
                )}
                {compose.excelKind === 'append_rows' && (
                  <div>
                    <label className="block text-xs text-muted mb-1">{t('office.edit.rows')}</label>
                    <textarea
                      value={compose.rowsText}
                      onChange={(e) => setField('rowsText')(e.target.value)}
                      rows={4}
                      className={inputClass}
                      data-testid="office-edit-rows"
                    />
                  </div>
                )}
              </div>
    );
  }
  return (
              <div className="space-y-2" data-testid="office-edit-form-ppt">
                <div>
                  <label className="block text-xs text-muted mb-1">{t('office.edit.opKind')}</label>
                  <select
                    value={compose.pptKind}
                    onChange={(e) => setField('pptKind')(e.target.value as PptEditKind)}
                    className={inputClass}
                    data-testid="office-edit-ppt-kind"
                  >
                    <option value="set_slide_title">{t('office.edit.kindSetTitle')}</option>
                    <option value="set_slide_bullets">{t('office.edit.kindSetBullets')}</option>
                    <option value="set_slide_notes">{t('office.edit.kindSetNotes')}</option>
                    <option value="append_slide">{t('office.edit.kindAppendSlide')}</option>
                    <option value="add_picture">{t('office.edit.kindAddPicture')}</option>
                  </select>
                </div>
                {compose.pptKind === 'append_slide' ? (
                  <>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.appendTitle')}
                      </label>
                      <input
                        type="text"
                        value={compose.appendTitle}
                        onChange={(e) => setField('appendTitle')(e.target.value)}
                        className={inputClass}
                        data-testid="office-edit-append-title"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.bullets')}
                      </label>
                      <textarea
                        value={compose.bulletsText}
                        onChange={(e) => setField('bulletsText')(e.target.value)}
                        rows={3}
                        className={inputClass}
                        data-testid="office-edit-bullets"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.notes')}
                      </label>
                      <textarea
                        value={compose.appendNotes}
                        onChange={(e) => setField('appendNotes')(e.target.value)}
                        rows={2}
                        className={inputClass}
                        data-testid="office-edit-append-notes"
                      />
                    </div>
                  </>
                ) : compose.pptKind === 'add_picture' ? (
                  <>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.pptSlideNumber')}
                      </label>
                      <input
                        type="number"
                        min={1}
                        value={compose.pictureIndex}
                        onChange={(e) => setField('pictureIndex')(e.target.value)}
                        className={inputClass}
                        data-testid="office-edit-picture-index"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.imagePath')}
                      </label>
                      <input
                        type="text"
                        value={compose.picturePath}
                        onChange={(e) => setField('picturePath')(e.target.value)}
                        placeholder={t('office.edit.imagePathPlaceholder')}
                        className={inputClass}
                        data-testid="office-edit-picture-path"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.imageWidth')}
                        </label>
                        <input
                          type="number"
                          min={0.1}
                          step={0.1}
                          value={compose.pictureWidth}
                          onChange={(e) => setField('pictureWidth')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-picture-width"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.imageHeight')}
                        </label>
                        <input
                          type="number"
                          min={0.1}
                          step={0.1}
                          value={compose.pictureHeight}
                          onChange={(e) => setField('pictureHeight')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-picture-height"
                        />
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.pptSlideNumber')}
                      </label>
                      <input
                        type="number"
                        min={1}
                        value={compose.slideNumber}
                        onChange={(e) => setField('slideNumber')(e.target.value)}
                        className={inputClass}
                        data-testid="office-edit-slide-number"
                      />
                    </div>
                    {compose.pptKind === 'set_slide_title' && (
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.pptTitle')}
                        </label>
                        <input
                          type="text"
                          value={compose.slideTitle}
                          onChange={(e) => setField('slideTitle')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-slide-title"
                        />
                      </div>
                    )}
                    {compose.pptKind === 'set_slide_bullets' && (
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.bullets')}
                        </label>
                        <textarea
                          value={compose.bulletsText}
                          onChange={(e) => setField('bulletsText')(e.target.value)}
                          rows={4}
                          className={inputClass}
                          data-testid="office-edit-bullets"
                        />
                      </div>
                    )}
                    {compose.pptKind === 'set_slide_notes' && (
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.notes')}
                        </label>
                        <textarea
                          value={compose.notesText}
                          onChange={(e) => setField('notesText')(e.target.value)}
                          rows={3}
                          className={inputClass}
                          data-testid="office-edit-notes"
                        />
                      </div>
                    )}
                  </>
                )}
              </div>
  );
}
