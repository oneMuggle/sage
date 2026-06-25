import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import { I18nProvider } from '../i18n';
import { SortableSessionItem } from './sortableItem';

describe('SortableSessionItem', () => {
  it('renders a drag handle with the i18n title', () => {
    render(
      <I18nProvider>
        <ul>
          <SortableSessionItem id="x" label="my session">
            <li>my session</li>
          </SortableSessionItem>
        </ul>
      </I18nProvider>,
    );
    expect(screen.getByLabelText('拖拽排序')).toBeInTheDocument();
  });
});
