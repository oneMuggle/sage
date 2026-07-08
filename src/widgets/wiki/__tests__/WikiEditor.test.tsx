import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import { useWikiStore } from '../../../entities/wiki/store';
import { WikiEditor } from '../WikiEditor';

// `editContent` and `isEditing` live as local useState inside WikiEditor
// (not in the store). The brief's original spy-on-store approach cannot
// observe them, so this test verifies the same behavioral contract —
// "editContent re-syncs when fileContent changes" — by inspecting the
// rendered textarea / preview after a file switch.

describe('WikiEditor', () => {
  it('re-syncs editContent when fileContent changes', () => {
    useWikiStore.setState({
      selectedFile: 'wiki/foo.md',
      fileContent: 'first',
      isLoading: false,
    });
    const { rerender } = render(<WikiEditor />);

    // Enter edit mode — the 编辑 button copies fileContent into local
    // editContent, so the textarea starts showing 'first'.
    fireEvent.click(screen.getByText(/^编辑$/));
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('first');

    // Switch to a different file. With the bug (useState initializer
    // runs only once), editContent would remain 'first' on rerender
    // and isEditing would stay true, so the textarea would still show
    // stale 'first'. With the fix (useEffect on [fileContent]),
    // editContent resets to 'second' and isEditing flips back to
    // false, so the textarea is unmounted.
    act(() => {
      useWikiStore.setState({ fileContent: 'second' });
    });
    rerender(<WikiEditor />);

    expect(screen.queryByRole('textbox')).toBeNull();
    // After the useEffect runs, MarkdownPreview re-renders with the
    // new fileContent — sanity check that we are showing the new file.
    expect(screen.getByText('second')).toBeInTheDocument();
  });
});
