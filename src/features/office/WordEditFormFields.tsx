import type { Dispatch, SetStateAction } from 'react';

import { useI18n } from '../../shared/lib/i18n';

import type { ComposeState, WordEditKind } from './OfficeEditPreviewDialog';

export interface WordEditFormFieldsProps {
  compose: ComposeState;
  setCompose: Dispatch<SetStateAction<ComposeState>>;
  setField: (key: keyof ComposeState) => (value: string) => void;
  inputClass: string;
}

export function WordEditFormFields({
  compose,
  setCompose,
  setField,
  inputClass,
}: WordEditFormFieldsProps) {
  const { t } = useI18n();
  return (
              <div className="space-y-2" data-testid="office-edit-form-word">
                <div>
                  <label className="block text-xs text-muted mb-1">{t('office.edit.opKind')}</label>
                  <select
                    value={compose.wordKind}
                    onChange={(e) => setField('wordKind')(e.target.value as WordEditKind)}
                    className={inputClass}
                    data-testid="office-edit-word-kind"
                  >
                    <option value="replace_text">{t('office.edit.kindReplaceText')}</option>
                    <option value="append_paragraphs">
                      {t('office.edit.kindAppendParagraphs')}
                    </option>
                    <option value="set_table_cell">{t('office.edit.kindSetTableCell')}</option>
                    <option value="delete_paragraph">{t('office.edit.kindDeleteParagraph')}</option>
                    <option value="add_comment">{t('office.edit.kindAddComment')}</option>
                    <option value="set_paragraph_style">{t('office.edit.kindSetStyle')}</option>
                    <option value="delete_comment">{t('office.edit.kindDeleteComment')}</option>
                    <option value="add_image">{t('office.edit.kindAddImage')}</option>
                  </select>
                </div>
                {compose.wordKind === 'replace_text' && (
                  <>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.wordFind')}
                      </label>
                      <input
                        type="text"
                        value={compose.find}
                        onChange={(e) => setField('find')(e.target.value)}
                        placeholder={t('office.edit.wordFindPlaceholder')}
                        className={inputClass}
                        data-testid="office-edit-find"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.wordReplace')}
                      </label>
                      <input
                        type="text"
                        value={compose.replace}
                        onChange={(e) => setField('replace')(e.target.value)}
                        placeholder={t('office.edit.wordReplacePlaceholder')}
                        className={inputClass}
                        data-testid="office-edit-replace"
                      />
                    </div>
                  </>
                )}
                {compose.wordKind === 'append_paragraphs' && (
                  <>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.paragraphs')}
                      </label>
                      <textarea
                        value={compose.paragraphsText}
                        onChange={(e) => setField('paragraphsText')(e.target.value)}
                        rows={4}
                        className={inputClass}
                        data-testid="office-edit-paragraphs"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.paraHeading')}
                      </label>
                      <select
                        value={compose.paraHeading}
                        onChange={(e) =>
                          setField('paraHeading')(e.target.value as ComposeState['paraHeading'])
                        }
                        className={inputClass}
                        data-testid="office-edit-para-heading"
                      >
                        <option value="">{t('office.edit.headingNone')}</option>
                        <option value="h1">h1</option>
                        <option value="h2">h2</option>
                        <option value="h3">h3</option>
                      </select>
                    </div>
                  </>
                )}
                {compose.wordKind === 'set_table_cell' && (
                  <>
                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.tableIndex')}
                        </label>
                        <input
                          type="number"
                          min={0}
                          value={compose.tableIndex}
                          onChange={(e) => setField('tableIndex')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-table-index"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.tableRow')}
                        </label>
                        <input
                          type="number"
                          min={0}
                          value={compose.tableRow}
                          onChange={(e) => setField('tableRow')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-table-row"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.tableCol')}
                        </label>
                        <input
                          type="number"
                          min={0}
                          value={compose.tableCol}
                          onChange={(e) => setField('tableCol')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-table-col"
                        />
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.tableText')}
                      </label>
                      <input
                        type="text"
                        value={compose.tableText}
                        onChange={(e) => setField('tableText')(e.target.value)}
                        className={inputClass}
                        data-testid="office-edit-table-text"
                      />
                    </div>
                  </>
                )}
                {compose.wordKind === 'set_paragraph_style' && (
                  <>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.styleMatch')}
                        </label>
                        <input
                          type="text"
                          value={compose.styleMatch}
                          onChange={(e) => setField('styleMatch')(e.target.value)}
                          placeholder={t('office.edit.styleMatchPlaceholder')}
                          className={inputClass}
                          data-testid="office-edit-style-match"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.styleIndex')}
                        </label>
                        <input
                          type="number"
                          min={0}
                          value={compose.styleIndex}
                          onChange={(e) => setField('styleIndex')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-style-index"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.styleFontSize')}
                        </label>
                        <input
                          type="number"
                          min={1}
                          value={compose.styleFontSize}
                          onChange={(e) => setField('styleFontSize')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-style-font-size"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.styleColor')}
                        </label>
                        <input
                          type="text"
                          value={compose.styleColor}
                          onChange={(e) => setField('styleColor')(e.target.value)}
                          placeholder="FF0000"
                          className={inputClass}
                          data-testid="office-edit-style-color"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.styleAlign')}
                        </label>
                        <select
                          value={compose.styleAlign}
                          onChange={(e) => setField('styleAlign')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-style-align"
                        >
                          <option value="">{t('office.edit.headingNone')}</option>
                          <option value="left">left</option>
                          <option value="center">center</option>
                          <option value="right">right</option>
                          <option value="justify">justify</option>
                        </select>
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                      <label className="flex items-center gap-2 text-xs text-text-secondary">
                        <input
                          type="checkbox"
                          checked={compose.styleBold}
                          onChange={(e) =>
                            setCompose((pr) => ({ ...pr, styleBold: e.target.checked }))
                          }
                          className="accent-primary"
                          data-testid="office-edit-style-bold"
                        />
                        {t('office.edit.styleBold')}
                      </label>
                      <label className="flex items-center gap-2 text-xs text-text-secondary">
                        <input
                          type="checkbox"
                          checked={compose.styleItalic}
                          onChange={(e) =>
                            setCompose((pr) => ({ ...pr, styleItalic: e.target.checked }))
                          }
                          className="accent-primary"
                          data-testid="office-edit-style-italic"
                        />
                        {t('office.edit.styleItalic')}
                      </label>
                    </div>
                  </>
                )}
                {compose.wordKind === 'add_image' && (
                  <>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.imagePath')}
                      </label>
                      <input
                        type="text"
                        value={compose.imagePath}
                        onChange={(e) => setField('imagePath')(e.target.value)}
                        placeholder={t('office.edit.imagePathPlaceholder')}
                        className={inputClass}
                        data-testid="office-edit-image-path"
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
                          value={compose.imageWidth}
                          onChange={(e) => setField('imageWidth')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-image-width"
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
                          value={compose.imageHeight}
                          onChange={(e) => setField('imageHeight')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-image-height"
                        />
                      </div>
                    </div>
                  </>
                )}
                {compose.wordKind === 'delete_comment' && (
                  <div>
                    <label className="block text-xs text-muted mb-1">
                      {t('office.edit.commentId')}
                    </label>
                    <input
                      type="text"
                      value={compose.commentId}
                      onChange={(e) => setField('commentId')(e.target.value)}
                      placeholder={t('office.edit.commentIdPlaceholder')}
                      className={inputClass}
                      data-testid="office-edit-comment-id"
                    />
                  </div>
                )}
                {compose.wordKind === 'add_comment' && (
                  <>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.wordFind')}
                      </label>
                      <input
                        type="text"
                        value={compose.deleteFind}
                        onChange={(e) => setField('deleteFind')(e.target.value)}
                        placeholder={t('office.edit.deleteFindPlaceholder')}
                        className={inputClass}
                        data-testid="office-edit-delete-find"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.commentText')}
                      </label>
                      <textarea
                        value={compose.commentText}
                        onChange={(e) => setField('commentText')(e.target.value)}
                        rows={3}
                        className={inputClass}
                        data-testid="office-edit-comment-text"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.commentAuthor')}
                      </label>
                      <input
                        type="text"
                        value={compose.commentAuthor}
                        onChange={(e) => setField('commentAuthor')(e.target.value)}
                        className={inputClass}
                        data-testid="office-edit-comment-author"
                      />
                    </div>
                  </>
                )}
                {compose.wordKind === 'delete_paragraph' && (
                  <>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.wordFind')}
                      </label>
                      <input
                        type="text"
                        value={compose.deleteFind}
                        onChange={(e) => setField('deleteFind')(e.target.value)}
                        placeholder={t('office.edit.deleteFindPlaceholder')}
                        className={inputClass}
                        data-testid="office-edit-delete-find"
                      />
                    </div>
                    <label className="flex items-center gap-2 text-xs text-text-secondary">
                      <input
                        type="checkbox"
                        checked={compose.deleteAll}
                        onChange={(e) => setCompose((p) => ({ ...p, deleteAll: e.target.checked }))}
                        className="accent-primary"
                        data-testid="office-edit-delete-all"
                      />
                      {t('office.edit.deleteAll')}
                    </label>
                  </>
                )}
              </div>
  );
}
